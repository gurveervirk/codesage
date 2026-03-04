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

def _resolve_relative_import(level: int, module: Optional[str], module_fqn: str, is_package: bool = False) -> str:
    """Helper to resolve relative imports."""
    if level == 0:
        return module or ""
        
    parts = module_fqn.split('.')
    # For __init__.py files (packages), the full module_fqn IS the package path.
    # For regular modules, remove the last component to get the package path.
    package_parts = parts if is_package else parts[:-1]
    
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

def _extract_imports_map(source_code: str, module_fqn: str, is_package: bool = False) -> Dict[str, str]:
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
            resolved_module = _resolve_relative_import(node.level, node.module, module_fqn, is_package)
            
            for alias in node.names:
                full_name = f"{resolved_module}.{alias.name}" if resolved_module else alias.name
                name = alias.asname or alias.name
                aliases[name] = full_name

    return aliases

def _collect_all_exports_from_ast(tree_body, conditional_blocks: List[Dict]) -> set:
    """Collect __all__ entries from all sources: regular assignments, augmented, method calls, conditionals."""
    all_exports = set()

    def _collect_from_ast_body(body):
        for node in body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "__all__":
                        if isinstance(node.value, ast.List):
                            for elt in node.value.elts:
                                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                    all_exports.add(elt.value)
                                elif isinstance(elt, ast.Str):
                                    all_exports.add(elt.s)
            elif isinstance(node, ast.AugAssign):
                if isinstance(node.target, ast.Name) and node.target.id == "__all__":
                    if isinstance(node.value, ast.List):
                        for elt in node.value.elts:
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                all_exports.add(elt.value)
                            elif isinstance(elt, ast.Str):
                                all_exports.add(elt.s)
            elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                call = node.value
                if (isinstance(call.func, ast.Attribute) and
                        isinstance(call.func.value, ast.Name) and
                        call.func.value.id == "__all__"):
                    method = call.func.attr
                    if method == 'append' and call.args:
                        arg = call.args[0]
                        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                            all_exports.add(arg.value)
                    elif method == 'extend' and call.args:
                        arg = call.args[0]
                        if isinstance(arg, ast.List):
                            for elt in arg.elts:
                                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                    all_exports.add(elt.value)

    _collect_from_ast_body(tree_body)

    for block in (conditional_blocks or []):
        for raw_var in block.get('variables', []):
            if raw_var.get('name') == '__all__':
                value_str = raw_var.get('value', '')
                try:
                    val_node = ast.parse(value_str, mode='eval').body
                    if isinstance(val_node, ast.List):
                        for elt in val_node.elts:
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                all_exports.add(elt.value)
                except Exception:
                    pass

    return all_exports


def _process_exports(
    source_code: str, 
    module_fqn: str, 
    module_entity: Entity,
    conditional_blocks: Optional[List[Dict]] = None,
    is_package: bool = False,
) -> Dict[str, List]:
    """Extract export info (re-exports, wildcards, __all__) including augmented __all__ and conditionals."""
    other_relations = defaultdict(list)
    if not source_code:
        return other_relations
        
    try:
        tree = ast.parse(source_code)
    except Exception:
        return other_relations

    all_exports = _collect_all_exports_from_ast(tree.body, conditional_blocks)

    def _process_import_nodes(nodes, condition: Optional[str] = None):
        for node in nodes:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    is_explicit = alias.asname and alias.asname == alias.name
                    local_name = alias.asname if alias.asname else alias.name.split('.')[0]
                    if is_explicit or local_name in all_exports:
                        target = alias.name
                        attrs = {"lineno": getattr(node, 'lineno', None)}
                        if condition:
                            attrs["condition"] = condition
                        ref = ExternalEntityRef(name=target, version=None, alias=local_name, attributes=attrs)
                        other_relations["EXPOSES"].append((module_entity.content_hash, ref))
            elif isinstance(node, ast.ImportFrom):
                resolved_module = _resolve_relative_import(node.level, node.module, module_fqn, is_package)
                if not node.names:
                    continue
                if any(a.name == '*' for a in node.names):
                    if resolved_module:
                        attrs = {"lineno": getattr(node, 'lineno', None)}
                        if condition:
                            attrs["condition"] = condition
                        ref = ExternalEntityRef(name=resolved_module, version=None, attributes=attrs)
                        other_relations["EXPOSES_ALL"].append((module_entity.content_hash, ref))
                    continue
                for alias in node.names:
                    is_explicit = alias.asname and alias.asname == alias.name
                    local_name = alias.asname if alias.asname else alias.name
                    if (is_explicit or local_name in all_exports) and resolved_module:
                        target = f"{resolved_module}.{alias.name}"
                        attrs = {"lineno": getattr(node, 'lineno', None)}
                        if condition:
                            attrs["condition"] = condition
                        ref = ExternalEntityRef(name=target, version=None, alias=local_name, attributes=attrs)
                        other_relations["EXPOSES"].append((module_entity.content_hash, ref))

    _process_import_nodes(tree.body)

    for block in (conditional_blocks or []):
        condition = block.get('condition')
        raw_imports = block.get('imports', [])
        if not raw_imports:
            continue
        try:
            stmts = []
            for imp in raw_imports:
                parsed_imp = ast.parse(imp['source'], mode='exec')
                stmts.extend(parsed_imp.body)
            _process_import_nodes(stmts, condition=condition)
        except Exception:
            pass

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
    if implementation_data.get('args'):
        main_entity.properties['args'] = implementation_data['args']
    if implementation_data.get('return_type'):
        main_entity.properties['return_type'] = implementation_data['return_type']
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
        if ov_data.get('args'):
            ov_entity.properties['args'] = ov_data['args']
        if ov_data.get('return_type'):
            ov_entity.properties['return_type'] = ov_data['return_type']
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

def _process_variable(
    data: Dict[str, Any],
    parent_fqn: str,
    parent_entity: Entity,
    version: Optional[str],
    condition: Optional[str] = None
) -> Tuple[List[Entity], List[Relationship]]:
    """Create a VARIABLE entity and HAS_VARIABLE relationship for a module-level assignment."""
    entities = []
    relations = []

    name = data.get('name', '')
    if not name or name.startswith('__'):
        return entities, relations

    fqn = f"{parent_fqn}.{name}"

    labels = ["VARIABLE"]
    if data.get('is_all_caps'):
        labels.append("CONSTANT")
    if data.get('is_type_alias'):
        labels.append("TYPE_ALIAS")
    if version:
        labels.append(f"version:{version}")

    properties: Dict[str, Any] = {"__name__": name}
    if data.get('value') is not None:
        properties['value'] = str(data['value'])[:512]
    if data.get('type_annotation'):
        properties['type_annotation'] = data['type_annotation']
    if condition:
        properties['condition'] = condition

    var_entity = Entity(
        name=fqn,
        labels=labels,
        properties=properties,
        content_hash=_hash_exact_source(data.get('source', ''), fqn),
    )
    var_entity.type = "VARIABLE"
    entities.append(var_entity)
    relations.append(Relationship(parent_entity, var_entity, "HAS_VARIABLE", {}))

    p_ents, p_rels = _create_property_entities_and_relations(var_entity, data, version)
    entities.extend(p_ents)
    relations.extend(p_rels)

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

    # Class-Level Variables
    for var_data in data.get('class_variables', []):
        var_name = var_data.get('name', '')
        if not var_name or var_name.startswith('__'):
            continue
        v_ents, v_rels = _process_variable(var_data, fqn, cls_entity, version)
        entities.extend(v_ents)
        relations.extend(v_rels)

    return entities, relations, other_relations

def _flatten_conditional_blocks(blocks: List[Dict]) -> List[Dict]:
    """Recursively flatten nested_blocks into a single list, preserving parent_block_start_line on each entry."""
    result = []
    for block in blocks:
        result.append(block)
        nested = block.get('nested_blocks', [])
        if nested:
            result.extend(_flatten_conditional_blocks(nested))
    return result


def convert_module(
    data: Dict[str, Any], 
    fqn: str, 
    version: Optional[str]
) -> Tuple[List[Entity], List[Relationship], Dict[str, List], List[Dict]]:
    """
    Convert parsed module data into entities, relationships, other_relations, and a symbol map.
    Returns (entities, relations, other_relations, symbol_map).
    """
    entities = []
    relations = []
    other_relations = defaultdict(list)
    symbol_map: List[Dict] = []

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
    is_package = (file_path or "").endswith(('__init__.py', '__init__.pyi'))
    alias_map = _extract_imports_map(source_content, fqn, is_package)
    
    conditional_blocks = _flatten_conditional_blocks(data.get('conditional_blocks', []))

    export_relations = _process_exports(source_content, fqn, module_entity, conditional_blocks, is_package)
    for k, v in export_relations.items():
        other_relations[k].extend(v)
    
    root_package = fqn.split('.')[0]

    defined_names: Set[str] = set()

    local_class_names = {c['name'] for c in data.get('classes', [])}
    for block in conditional_blocks:
        for c in block.get('classes', []):
            local_class_names.add(c['name'])

    for cls_data in data.get('classes', []):
        defined_names.add(cls_data['name'])
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
        symbol_map.append({
            "name": cls_data['name'],
            "origin": "defined",
            "entity_fqn": f"{fqn}.{cls_data['name']}",
            "source_fqn": None,
            "condition": None,
            "line_no": cls_data.get('lineno'),
            "parent_block_start_line": None,
            "is_reexport": False,
        })

    functions_map: Dict[str, List] = defaultdict(list)
    for func_data in data.get('functions', []):
        functions_map[func_data['name']].append(func_data)
        
    for func_name, func_group in functions_map.items():
        defined_names.add(func_name)
        f_ents, f_rels = _process_function_group(
            func_name, func_group, fqn, module_entity, version, is_method=False
        )
        entities.extend(f_ents)
        relations.extend(f_rels)
        symbol_map.append({
            "name": func_name,
            "origin": "defined",
            "entity_fqn": f"{fqn}.{func_name}",
            "source_fqn": None,
            "condition": None,
            "line_no": func_group[0].get('lineno') if func_group else None,
            "parent_block_start_line": None,
            "is_reexport": False,
        })

    for var_data in data.get('variables', []):
        var_name = var_data.get('name', '')
        if not var_name or var_name.startswith('__'):
            continue
        defined_names.add(var_name)
        v_ents, v_rels = _process_variable(var_data, fqn, module_entity, version)
        entities.extend(v_ents)
        relations.extend(v_rels)
        symbol_map.append({
            "name": var_name,
            "origin": "defined",
            "entity_fqn": f"{fqn}.{var_name}",
            "source_fqn": None,
            "condition": None,
            "line_no": var_data.get('lineno'),
            "parent_block_start_line": None,
            "is_reexport": var_data.get('is_all_caps', False),
        })

    for block in conditional_blocks:
        condition = block.get('condition')
        branch = block.get('branch')
        parent_block_start_line = block.get('parent_block_start_line')

        for cls_data in block.get('classes', []):
            if cls_data['name'] in defined_names:
                symbol_map.append({
                    "name": cls_data['name'],
                    "origin": "defined",
                    "entity_fqn": f"{fqn}.{cls_data['name']}",
                    "source_fqn": None,
                    "condition": condition,
                    "line_no": cls_data.get('lineno'),
                    "parent_block_start_line": parent_block_start_line,
                    "is_reexport": False,
                })
                continue
            defined_names.add(cls_data['name'])
            c_ents, c_rels, c_others = convert_class(
                cls_data, fqn, fqn, version, alias_map, root_package, local_class_names
            )
            for e in c_ents:
                if "CLASS" in e.labels and "CONDITION" not in e.labels:
                    if condition:
                        e.properties['condition'] = condition
            entities.extend(c_ents)
            relations.extend(c_rels)
            cls_entity = next((e for e in c_ents if e.name == f"{fqn}.{cls_data['name']}" and "CLASS" in e.labels), None)
            if cls_entity:
                relations.append(Relationship(module_entity, cls_entity, "HAS_CLASS", {}))
            for k, v in c_others.items():
                other_relations[k].extend(v)
            symbol_map.append({
                "name": cls_data['name'],
                "origin": "defined",
                "entity_fqn": f"{fqn}.{cls_data['name']}",
                "source_fqn": None,
                "condition": condition,
                "line_no": cls_data.get('lineno'),
                "parent_block_start_line": parent_block_start_line,
                "is_reexport": False,
            })

        cond_func_map: Dict[str, List] = defaultdict(list)
        for func_data in block.get('functions', []):
            cond_func_map[func_data['name']].append(func_data)
        for func_name, func_group in cond_func_map.items():
            if func_name in defined_names:
                symbol_map.append({
                    "name": func_name,
                    "origin": "defined",
                    "entity_fqn": f"{fqn}.{func_name}",
                    "source_fqn": None,
                    "condition": condition,
                    "line_no": func_group[0].get('lineno') if func_group else None,
                    "parent_block_start_line": parent_block_start_line,
                    "is_reexport": False,
                })
                continue
            defined_names.add(func_name)
            f_ents, f_rels = _process_function_group(
                func_name, func_group, fqn, module_entity, version, is_method=False
            )
            for e in f_ents:
                if ("FUNCTION" in e.labels or "METHOD" in e.labels) and condition:
                    e.properties['condition'] = condition
            entities.extend(f_ents)
            relations.extend(f_rels)
            symbol_map.append({
                "name": func_name,
                "origin": "defined",
                "entity_fqn": f"{fqn}.{func_name}",
                "source_fqn": None,
                "condition": condition,
                "line_no": func_group[0].get('lineno') if func_group else None,
                "parent_block_start_line": parent_block_start_line,
                "is_reexport": False,
            })

        for var_data in block.get('variables', []):
            var_name = var_data.get('name', '')
            if not var_name or var_name.startswith('__'):
                continue
            if var_name in defined_names:
                symbol_map.append({
                    "name": var_name,
                    "origin": "defined",
                    "entity_fqn": f"{fqn}.{var_name}",
                    "source_fqn": None,
                    "condition": condition,
                    "line_no": var_data.get('lineno'),
                    "parent_block_start_line": parent_block_start_line,
                    "is_reexport": var_data.get('is_all_caps', False),
                })
                continue
            defined_names.add(var_name)
            v_ents, v_rels = _process_variable(var_data, fqn, module_entity, version, condition=condition)
            entities.extend(v_ents)
            relations.extend(v_rels)
            symbol_map.append({
                "name": var_name,
                "origin": "defined",
                "entity_fqn": f"{fqn}.{var_name}",
                "source_fqn": None,
                "condition": condition,
                "line_no": var_data.get('lineno'),
                "parent_block_start_line": parent_block_start_line,
                "is_reexport": var_data.get('is_all_caps', False),
            })

        for imp in block.get('imports', []):
            try:
                parsed_imp = ast.parse(imp['source'], mode='exec')
                for node in parsed_imp.body:
                    if isinstance(node, ast.ImportFrom):
                        resolved_module = _resolve_relative_import(node.level, node.module, fqn, is_package)
                        for alias in node.names:
                            if alias.name == '*':
                                symbol_map.append({
                                    "name": f"*",
                                    "origin": "wildcard",
                                    "entity_fqn": None,
                                    "source_fqn": resolved_module,
                                    "condition": condition,
                                    "line_no": imp.get('lineno'),
                                    "is_reexport": False,
                                })
                            else:
                                local_name = alias.asname if alias.asname else alias.name
                                target = f"{resolved_module}.{alias.name}" if resolved_module else alias.name
                                if local_name not in defined_names:
                                    symbol_map.append({
                                        "name": local_name,
                                        "origin": "imported",
                                        "entity_fqn": None,
                                        "source_fqn": target,
                                        "condition": condition,
                                        "line_no": imp.get('lineno'),
                                        "is_reexport": False,
                                    })
                    elif isinstance(node, ast.Import):
                        for alias in node.names:
                            local_name = alias.asname if alias.asname else alias.name.split('.')[0]
                            if local_name not in defined_names:
                                symbol_map.append({
                                    "name": local_name,
                                    "origin": "imported",
                                    "entity_fqn": None,
                                    "source_fqn": alias.name,
                                    "condition": condition,
                                    "line_no": imp.get('lineno'),
                                    "is_reexport": False,
                                })
            except Exception:
                pass

    try:
        tree = ast.parse(source_content)
        for node in tree.body:
            if isinstance(node, ast.ImportFrom):
                resolved_module = _resolve_relative_import(node.level, node.module, fqn, is_package)
                for alias in node.names:
                    if alias.name == '*':
                        symbol_map.append({
                            "name": "*",
                            "origin": "wildcard",
                            "entity_fqn": None,
                            "source_fqn": resolved_module,
                            "condition": None,
                            "line_no": node.lineno,
                            "is_reexport": False,
                        })
                    else:
                        local_name = alias.asname if alias.asname else alias.name
                        if local_name not in defined_names:
                            target = f"{resolved_module}.{alias.name}" if resolved_module else alias.name
                            is_explicit = alias.asname and alias.asname == alias.name
                            symbol_map.append({
                                "name": local_name,
                                "origin": "imported",
                                "entity_fqn": None,
                                "source_fqn": target,
                                "condition": None,
                                "line_no": node.lineno,
                                "is_reexport": is_explicit,
                            })
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    local_name = alias.asname if alias.asname else alias.name.split('.')[0]
                    if local_name not in defined_names:
                        is_explicit = alias.asname and alias.asname == alias.name
                        symbol_map.append({
                            "name": local_name,
                            "origin": "imported",
                            "entity_fqn": None,
                            "source_fqn": alias.name,
                            "condition": None,
                            "line_no": node.lineno,
                            "is_reexport": is_explicit,
                        })
    except Exception:
        pass

    return entities, relations, other_relations, symbol_map
