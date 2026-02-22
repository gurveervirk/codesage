"""
Static Entity Builder using Tree-sitter parsed data.
Adapts the legacy entity_builder logic for static analysis.
"""

import json
import ast
import hashlib
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple, Set

from ..models import Entity, Relationship, ExternalEntityRef


def _hash_exact_source(source: str, fallback_name: str) -> str:
    if source:
        h = hashlib.sha256()
        h.update(source.encode("utf-8", errors="ignore"))
        return h.hexdigest()
    h = hashlib.sha256()
    h.update(fallback_name.encode("utf-8", errors="ignore"))
    return h.hexdigest()

def _resolve_relative_import(level: int, module: Optional[str], module_fqn: str) -> str:
    """Helper to resolve relative imports."""
    if level == 0:
        return module or ""
        
    parts = module_fqn.split('.')
    # Remove module name to get package path
    package_parts = parts[:-1]
    
    # level 1: from . import -> current package (steps_up = 0)
    # level 2: from .. import -> parent package (steps_up = 1)
    steps_up = level - 1
    
    if steps_up > len(package_parts):
        base_parts = []
    else:
        end_idx = len(package_parts) - steps_up
        base_parts = package_parts[:end_idx]
        
    base_str = ".".join(base_parts)
    if module:
        return f"{base_str}.{module}" if base_str else module
    return base_str

def _extract_imports_map(source_code: str, module_fqn: str) -> Dict[str, str]:
    """Map alias -> full_path for top-level imports."""
    aliases = {}
    if not source_code:
        return aliases
        
    try:
        tree = ast.parse(source_code)
    except Exception:
        return aliases

    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                top_level = alias.name.split('.')[0]
                if alias.asname:
                    aliases[alias.asname] = alias.name
                else:
                    aliases[top_level] = top_level
                    
        elif isinstance(node, ast.ImportFrom):
            resolved_module = _resolve_relative_import(node.level, node.module, module_fqn)
            
            for alias in node.names:
                full_name = f"{resolved_module}.{alias.name}" if resolved_module else alias.name
                name = alias.asname or alias.name
                aliases[name] = full_name

    return aliases

def _process_exports(
    source_code: str, 
    module_fqn: str, 
    module_entity: Entity
) -> Dict[str, List]:
    """Extract export info (re-exports, wildcards, __all__)."""
    other_relations = defaultdict(list)
    if not source_code:
        return other_relations
        
    try:
        tree = ast.parse(source_code)
    except Exception:
        return other_relations

    # 1. Parse __all__
    all_exports = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__all__":
                    if isinstance(node.value, ast.List):
                        for elt in node.value.elts:
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                all_exports.add(elt.value)
                            elif isinstance(elt, ast.Str): 
                                all_exports.add(elt.s)
    
    # 2. Check imports
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                # Explicit export (import x as x) or in __all__
                is_explicit = alias.asname and alias.asname == alias.name
                local_name = alias.asname if alias.asname else alias.name.split('.')[0]
                
                if is_explicit or local_name in all_exports:
                    target = alias.name
                    ref = ExternalEntityRef(name=target, version=None, alias=local_name)
                    other_relations["EXPOSES"].append((module_entity.content_hash, ref))

        elif isinstance(node, ast.ImportFrom):
            resolved_module = _resolve_relative_import(node.level, node.module, module_fqn)
            if not node.names:
                continue

            # Wildcard export
            if any(a.name == '*' for a in node.names):
                 if resolved_module:
                    ref = ExternalEntityRef(name=resolved_module, version=None)
                    other_relations["EXPOSES_ALL"].append((module_entity.content_hash, ref))
                 continue

            for alias in node.names:
                is_explicit = alias.asname and alias.asname == alias.name
                local_name = alias.asname if alias.asname else alias.name
                
                if (is_explicit or local_name in all_exports) and resolved_module:
                    target = f"{resolved_module}.{alias.name}"
                    ref = ExternalEntityRef(name=target, version=None, alias=local_name)
                    other_relations["EXPOSES"].append((module_entity.content_hash, ref))

    return other_relations

def _create_property_entity(
    parent_name: str,
    property_type: str,
    value: Any,
    version: Optional[str] = None
) -> Entity:
    """
    Create a property entity (SIGNATURE, SOURCE, DOCSTRING, etc.).
    Adapted from entity_builder.py
    """
    name = f"{parent_name}::{property_type}"
    
    labels = [property_type]
    if version:
        labels.append(f"version:{version}")
    
    if isinstance(value, (dict, list)):
        value_str = json.dumps(value, sort_keys=True)
    else:
        value_str = str(value) if value is not None else ""
    
    properties = {"value": value_str}
    
    # We set content_hash implicitly or via properties in init, but here just setting explicit type
    ent = Entity(name=name, labels=labels, properties=properties)
    ent.type = property_type
    return ent

def _create_property_entities_and_relations(
    parent_entity: Entity,
    data: Dict[str, Any],
    version: Optional[str]
) -> Tuple[List[Entity], List[Relationship]]:
    """
    Create property entities (Source, Decorators, etc.) and relations for a parent entity.
    """
    prop_entities: List[Entity] = []
    prop_relations: List[Relationship] = []
    
    # Extract data
    is_module = "MODULE" in parent_entity.labels
    source_content = data.get("source", "")
    docstring = data.get("docstring")
    lineno = data.get("lineno")
    end_lineno = data.get("end_lineno")
    
    # Decorators
    decorators = data.get("decorators", [])

    # 1. SOURCE Entity
    # Always created if we have source info or docstring or signature
    if source_content or docstring or lineno or data.get("signature_start_line") is not None:
        name = f"{parent_entity.name}::SOURCE"
        labels = ["SOURCE"]
        if version:
            labels.append(f"version:{version}")
            
        properties = {}
        if is_module:
            if source_content:
                # Use "code" for source content in module_sources (from python_parser "source")
                properties["code"] = source_content
            if docstring:
                properties["docstring"] = docstring
            # Also propagate file_path if available in data, so it ends up in module_sources
            if data.get("file_path"):
                properties["file_path"] = data.get("file_path")
        else:
            # Non-module: store line numbers
            if lineno is not None:
                properties["line_start"] = lineno
            if end_lineno is not None:
                properties["line_end"] = end_lineno
            if data.get("docstring_start_line") is not None:
                properties["docstring_start_line"] = data.get("docstring_start_line")
            if data.get("docstring_end_line") is not None:
                properties["docstring_end_line"] = data.get("docstring_end_line")
            if data.get("signature_start_line") is not None:
                properties["signature_start_line"] = data.get("signature_start_line")
            if data.get("signature_end_line") is not None:
                properties["signature_end_line"] = data.get("signature_end_line")
                
        source_hash = parent_entity.content_hash if not is_module else None
        source_entity = Entity(name=name, labels=labels, properties=properties, content_hash=source_hash)
        source_entity.type = "SOURCE"
        prop_entities.append(source_entity)
        prop_relations.append(Relationship(
            parent_entity, source_entity, "HAS_SOURCE", {}
        ))

    # 2. DECORATOR_DETAILS Entity
    # TODO: Consider resolving decorators to imported entity paths in the parent module's source code, for more information.
    if decorators:
        # Match legacy structure: List of dicts with 'name'
        formatted_decorators = []
        for d in decorators:
            formatted_decorators.append({"name": d})
            
        decorator_value = {"decorators": formatted_decorators}
        decorator_entity = _create_property_entity(
            parent_entity.name, "DECORATOR_DETAILS", decorator_value, version
        )
        prop_entities.append(decorator_entity)
        prop_relations.append(Relationship(
            parent_entity, decorator_entity, "HAS_DECORATOR_DETAILS", {}
        ))
        
    return prop_entities, prop_relations

def _process_function_group(
    name: str,
    group: List[Dict[str, Any]],
    parent_fqn: str,
    parent_entity: Entity,
    version: Optional[str],
    is_method: bool
) -> Tuple[List[Entity], List[Relationship]]:
    """
    Process a group of functions with the same name (handling duplicates/overloads).
    """
    entities = []
    relations = []
    
    fqn = f"{parent_fqn}.{name}"
    base_labels = ["METHOD"] if is_method else ["FUNCTION"]
    
    # Separate implementation and overloads
    # Heuristic: implementations usually don't have @overload
    implementation_data = None
    overloads_data = []
    
    for f_data in group:
        decorators = f_data.get('decorators', [])
        # Check if any decorator string contains "overload"
        is_overload = any("overload" in d for d in decorators)
        
        if is_overload:
            overloads_data.append(f_data)
        else:
            if implementation_data is None:
                implementation_data = f_data
            else:
                # Multiple non-overload implementations processed as overloads/duplicates
                overloads_data.append(f_data)
                
    # If only overloads found (e.g. .pyi file), use the last one as main
    if implementation_data is None and overloads_data:
        implementation_data = overloads_data.pop() 

    if not implementation_data:
        return entities, relations

    # Main Entity
    main_labels = base_labels.copy()
    if overloads_data:
        main_labels.append("OVERLOADED")
    if version:
        main_labels.append(f"version:{version}")

    main_entity = Entity(
        name=fqn,
        labels=main_labels,
        properties={
            "__name__": name
        },
        content_hash=_hash_exact_source(implementation_data.get("source", ""), fqn),
    )
    main_entity.type = "METHOD" if is_method else "FUNCTION"
    entities.append(main_entity)
    relations.append(Relationship(
        parent_entity,
        main_entity,
        "HAS_METHOD" if is_method else "HAS_FUNCTION",
        {}
    ))
    
    # Main Properties
    p_ents, p_rels = _create_property_entities_and_relations(main_entity, implementation_data, version)
    entities.extend(p_ents)
    relations.extend(p_rels)
    
    # Overloads
    for ov_data in overloads_data:
        ov_labels = base_labels + ["OVERLOAD"]
        if version:
            ov_labels.append(f"version:{version}")
        
        ov_entity = Entity(
            name=fqn,
            labels=ov_labels,
            properties={
                "__name__": name
            },
            content_hash=_hash_exact_source(ov_data.get("source", ""), fqn),
        )
        ov_entity.type = "METHOD" if is_method else "FUNCTION"
        entities.append(ov_entity)
        relations.append(Relationship(
            parent_entity,
            ov_entity,
            "HAS_METHOD" if is_method else "HAS_FUNCTION",
            {}
        ))
        
        # Overload properties
        ov_p_ents, ov_p_rels = _create_property_entities_and_relations(ov_entity, ov_data, version)
        entities.extend(ov_p_ents)
        relations.extend(ov_p_rels)
        
    return entities, relations

def convert_class(
    data: Dict[str, Any], 
    parent_fqn: str, 
    module_fqn: str,
    version: Optional[str],
    alias_map: Dict[str, str],
    root_package: str,
    local_class_names: Set[str]
) -> Tuple[List[Entity], List[Relationship], Dict[str, List]]:
    
    entities = []
    relations = []
    other_relations = defaultdict(list)
    
    cls_name = data['name']
    fqn = f"{parent_fqn}.{cls_name}"
    
    # Class Entity
    cls_labels = ["CLASS"]
    if version:
        cls_labels.append(f"version:{version}")

    cls_entity = Entity(
        name=fqn,
        labels=cls_labels,
        properties={
            "__name__": cls_name
        },
        content_hash=_hash_exact_source(data.get("source", ""), fqn),
    )
    cls_entity.type = "CLASS"
    entities.append(cls_entity)
    
    # Properties
    c_props, c_rels = _create_property_entities_and_relations(cls_entity, data, version)
    entities.extend(c_props)
    relations.extend(c_rels)
    
    # Bases (Inheritance)
    mro_index = 0
    for base in data.get('bases', []):
        if not base or base == "object":
            continue

        base_parts = base.split('.')
        root = base_parts[0]
        resolved_fqn = None

        if root in alias_map:
            resolved_root = alias_map[root]
            if len(base_parts) > 1:
                resolved_fqn = f"{resolved_root}.{'.'.join(base_parts[1:])}"
            else:
                resolved_fqn = resolved_root
        elif root in local_class_names:
            resolved_fqn = f"{module_fqn}.{base}"

        final_target = resolved_fqn

        if final_target:
            rel_type = "EXTERNAL_INHERITS"
            if root_package and (final_target == root_package or final_target.startswith(f"{root_package}.")):
                rel_type = "INTERNAL_INHERITS"
            base_ref = ExternalEntityRef(
                name=final_target,
                version=None,
                attributes={"mro_index": mro_index, "resolvable": rel_type == "INTERNAL_INHERITS"},
            )
            other_relations[rel_type].append((cls_entity.content_hash, base_ref))
            mro_index += 1
        else:
            # TODO: Store for subsequent processing by checking wildcard imports
            pass

    # Methods grouping
    methods_map = defaultdict(list)
    for method_data in data.get('methods', []):
        methods_map[method_data['name']].append(method_data)
        
    for method_name, method_group in methods_map.items():
        m_ents, m_rels = _process_function_group(
            method_name, method_group, fqn, cls_entity, version, is_method=True
        )
        entities.extend(m_ents)
        relations.extend(m_rels)
        
    # Inner Classes
    for inner_cls in data.get('inner_classes', []):
        inner_fqn = f"{fqn}.{inner_cls['name']}"
        sub_entities, sub_rels, sub_others = convert_class(
            inner_cls, fqn, module_fqn, version, alias_map, root_package, local_class_names
        )
        entities.extend(sub_entities)
        relations.extend(sub_rels)
        inner_entity = next((e for e in sub_entities if e.name == inner_fqn and "CLASS" in e.labels), None)
        if inner_entity:
            relations.append(Relationship(cls_entity, inner_entity, "HAS_CLASS", {}))
        for k, v in sub_others.items():
            other_relations[k].extend(v)
            
    return entities, relations, other_relations

def convert_module(
    data: Dict[str, Any], 
    fqn: str, 
    version: Optional[str]
) -> Tuple[List[Entity], List[Relationship], Dict[str, List]]:
    """
    Convert parsed module data into entities and relationships.
    """
    entities = []
    relations = []
    other_relations = defaultdict(list)
    
    # 1. Module Entity
    module_labels = ["MODULE", "PYTHON_MODULE"]
    if version:
        module_labels.append(f"version:{version}")

    file_path = data.get('file_path')
    
    module_properties = {
        "file_path": file_path,
        "__name__": fqn.split('.')[-1]
    }
    
    module_entity = Entity(
        name=fqn,
        labels=module_labels,
        properties=module_properties
    )
    module_entity.type = "MODULE"
    entities.append(module_entity)
        
    m_props, m_rels = _create_property_entities_and_relations(module_entity, data, version)
    entities.extend(m_props)
    relations.extend(m_rels)
  
    source_content = data.get("source", "")
    alias_map = _extract_imports_map(source_content, fqn)
    
    # Process exports (EXPOSES, EXPOSES_ALL)
    export_relations = _process_exports(source_content, fqn, module_entity)
    for k, v in export_relations.items():
        other_relations[k].extend(v)
    
    root_package = fqn.split('.')[0]
    local_class_names = {c['name'] for c in data.get('classes', [])}
        
    # 2. Classes
    for cls_data in data.get('classes', []):
        c_ents, c_rels, c_others = convert_class(
            cls_data, fqn, fqn, version, alias_map, root_package, local_class_names
        )
        entities.extend(c_ents)
        relations.extend(c_rels)
        cls_entity = next((e for e in c_ents if e.name == f"{fqn}.{cls_data['name']}" and "CLASS" in e.labels), None)
        if cls_entity:
            relations.append(Relationship(module_entity, cls_entity, "HAS_CLASS", {}))
        for k, v in c_others.items():
            other_relations[k].extend(v)
        
    # 3. Functions
    functions_map = defaultdict(list)
    for func_data in data.get('functions', []):
        functions_map[func_data['name']].append(func_data)
        
    for func_name, func_group in functions_map.items():
        f_ents, f_rels = _process_function_group(
            func_name, func_group, fqn, module_entity, version, is_method=False
        )
        entities.extend(f_ents)
        relations.extend(f_rels)

    return entities, relations, other_relations
