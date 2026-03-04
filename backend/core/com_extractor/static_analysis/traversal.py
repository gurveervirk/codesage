"""
Static filesystem traversal for package extraction.
"""

import os
import re
import logging
from typing import List, Tuple, Generator, Dict, Any, Set

from ..models import Entity, Relationship
from .parsers.python_parser import PythonTreeSitterParser
from .builder import convert_module

_C_EXT_RE = re.compile(r'^([A-Za-z_][A-Za-z0-9_]*).*\.(so|pyd)$')

def find_python_files(root_path: str) -> Generator[str, None, None]:
    """Yield Python source files (.py preferred, .pyi as fallback when no .py exists)."""
    if os.path.isfile(root_path):
        if root_path.endswith('.py') or root_path.endswith('.pyi'):
            yield root_path
        return

    for root, _, files in os.walk(root_path):
        py_stems: Set[str] = set()
        pyi_stems: Dict[str, str] = {}

        for file in files:
            if file.endswith('.py'):
                stem = file[:-3]
                py_stems.add(stem)
                yield os.path.join(root, file)
            elif file.endswith('.pyi'):
                stem = file[:-4]
                pyi_stems[stem] = os.path.join(root, file)

        for stem, pyi_path in pyi_stems.items():
            if stem not in py_stems:
                yield pyi_path

def find_companion_stubs(root_path: str) -> Generator[str, None, None]:
    """Yield .pyi stub files that have a companion .py file in the same directory."""
    if os.path.isfile(root_path):
        return
    for root, _, files in os.walk(root_path):
        py_stems: Set[str] = set()
        pyi_paths: Dict[str, str] = {}
        for file in files:
            if file.endswith('.py'):
                py_stems.add(file[:-3])
            elif file.endswith('.pyi'):
                pyi_paths[file[:-4]] = os.path.join(root, file)
        for stem, pyi_path in pyi_paths.items():
            if stem in py_stems:
                yield pyi_path

def find_c_extension_modules(root_path: str, py_stems_seen: Set[str]) -> List[Tuple[str, str]]:
    """
    Return (module_simple_name, file_path) for C extension files that have no
    corresponding .py or .pyi source already discovered.
    """
    results = []
    if not os.path.isdir(root_path):
        return results
    for root, _, files in os.walk(root_path):
        for file in files:
            m = _C_EXT_RE.match(file)
            if not m:
                continue
            stem = m.group(1)
            if stem in py_stems_seen:
                continue
            results.append((stem, os.path.join(root, file)))
    return results

def get_module_fqn(file_path: str, root_path: str, package_name: str) -> str:
    """
    Calculate Fully Qualified Name from file path relative to root.
    Example: root/sub/mod.py -> package_name.sub.mod
             root/sub/mod.pyi -> package_name.sub.mod
    """
    rel_path = os.path.relpath(file_path, root_path)
    if rel_path.endswith('.pyi'):
        path_no_ext = rel_path[:-4]
    else:
        path_no_ext = os.path.splitext(rel_path)[0]
    
    if path_no_ext.endswith('__init__'):
         path_no_ext = os.path.dirname(path_no_ext)
         if not path_no_ext:
             return package_name
    
    if path_no_ext == '.':
        return package_name
        
    parts = path_no_ext.split(os.sep)
    parts = [p for p in parts if p]
    
    if not parts:
        return package_name
        
    return f"{package_name}.{'.'.join(parts)}"

def process_package_static(
    package_path: str, 
    package_name: str, 
    version: str,
    parser: PythonTreeSitterParser = None
) -> Tuple[List[Entity], List[Relationship], Dict[str, Any], Dict[str, List[Dict]]]:
    """
    Process a package directory statically.
    Returns (entities, relations, other_relations, module_symbol_maps).
    """
    if parser is None:
        parser = PythonTreeSitterParser()
        
    all_entities = []
    all_relations = []
    all_other_relations = {}
    module_symbol_maps: Dict[str, List[Dict]] = {}
    
    logging.info(f"Starting static extraction for {package_name} at {package_path}")
    
    base_dir = os.path.dirname(package_path)
    py_stems_seen: Set[str] = set()
    
    for file_path in find_python_files(package_path):
        is_stub = file_path.endswith('.pyi')
        try:
            fqn = get_module_fqn(file_path, package_path, package_name)
            stem = os.path.splitext(os.path.basename(file_path))[0]
            py_stems_seen.add(stem)

            parsed_data = parser.parse_file(file_path)
            
            if "site-packages" in file_path:
                rel_path = file_path.split("site-packages")[-1]
                rel_path = rel_path.lstrip(os.sep)
                parsed_data['file_path'] = rel_path
            else:
                try:
                    rel_path = os.path.relpath(file_path, base_dir)
                    parsed_data['file_path'] = rel_path
                except ValueError:
                    pass

            entities, relations, other_rels, symbol_map = convert_module(
                parsed_data, 
                fqn, 
                version
            )

            if is_stub:
                for e in entities:
                    if e.name == fqn and "MODULE" in e.labels and "STUB" not in e.labels:
                        e.labels.append("STUB")

            for k, v in other_rels.items():
                if k not in all_other_relations:
                    all_other_relations[k] = []
                all_other_relations[k].extend(v)
            
            all_entities.extend(entities)
            all_relations.extend(relations)
            if symbol_map:
                module_symbol_maps[fqn] = symbol_map
            
        except Exception as e:
            logging.error(f"Failed to process {file_path}: {e}")
            import traceback
            traceback.print_exc()

    entity_by_fqn: Dict[str, Any] = {e.name: e for e in all_entities}

    for stub_path in find_companion_stubs(package_path):
        try:
            fqn = get_module_fqn(stub_path, package_path, package_name)
            parsed_data = parser.parse_file(stub_path)
            if "site-packages" in stub_path:
                rel_path = stub_path.split("site-packages")[-1].lstrip(os.sep)
                parsed_data['file_path'] = rel_path
            else:
                try:
                    parsed_data['file_path'] = os.path.relpath(stub_path, base_dir)
                except ValueError:
                    pass
            stub_entities, stub_relations, stub_other_rels, stub_symbol_map = convert_module(parsed_data, fqn, version)

            stub_module_entity = None
            for stub_e in stub_entities:
                if stub_e.name == fqn and 'MODULE' in stub_e.labels:
                    stub_module_entity = stub_e
                    break
            existing_module = entity_by_fqn.get(fqn)
            if stub_module_entity is not None and existing_module is not None:
                existing_hash = existing_module.content_hash
                stub_module_hash = stub_module_entity.content_hash
                for rel_type in ("EXPOSES", "EXPOSES_ALL"):
                    if rel_type in stub_other_rels:
                        stub_other_rels[rel_type] = [
                            (existing_hash if h == stub_module_hash else h, ref)
                            for h, ref in stub_other_rels[rel_type]
                        ]
                all_entities.append(stub_module_entity)
                for stub_e in stub_entities:
                    if stub_e.name == f"{fqn}::SOURCE" and "SOURCE" in stub_e.labels:
                        all_entities.append(stub_e)
                        break

            for k, v in stub_other_rels.items():
                if k not in all_other_relations:
                    all_other_relations[k] = []
                all_other_relations[k].extend(v)

            if stub_symbol_map:
                existing_sym_map = module_symbol_maps.get(fqn)
                if existing_sym_map is None:
                    module_symbol_maps[fqn] = stub_symbol_map
                else:
                    existing_names = {s.get("name") for s in existing_sym_map}
                    for sym in stub_symbol_map:
                        if sym.get("name") not in existing_names:
                            existing_sym_map.append(sym)

            pre_stub_fqns = set(entity_by_fqn.keys())
            new_stub_fqns: Set[str] = set()
            for stub_e in stub_entities:
                if '::' in stub_e.name or 'MODULE' in stub_e.labels:
                    continue
                if stub_e.name in pre_stub_fqns:
                    existing = entity_by_fqn[stub_e.name]
                    if 'args' not in existing.properties and stub_e.properties.get('args'):
                        existing.properties['args'] = stub_e.properties['args']
                    if 'return_type' not in existing.properties and stub_e.properties.get('return_type'):
                        existing.properties['return_type'] = stub_e.properties['return_type']
                    if 'STUB_ENRICHED' not in existing.labels:
                        existing.labels.append('STUB_ENRICHED')
                else:
                    if 'STUB' not in stub_e.labels:
                        stub_e.labels.append('STUB')
                    stub_e.properties['_stub_module_fqn'] = fqn
                    all_entities.append(stub_e)
                    if stub_e.name not in entity_by_fqn:
                        entity_by_fqn[stub_e.name] = stub_e
                    new_stub_fqns.add(stub_e.name)
            if new_stub_fqns:
                for stub_e in stub_entities:
                    if '::' not in stub_e.name:
                        continue
                    parent_fqn = stub_e.name.split('::')[0]
                    if parent_fqn in new_stub_fqns:
                        all_entities.append(stub_e)
                for rel in stub_relations:
                    from_fqn = rel.from_entity.name
                    to_fqn = rel.to_entity.name if rel.to_entity else None
                    if from_fqn in new_stub_fqns or to_fqn in new_stub_fqns:
                        all_relations.append(rel)
        except Exception as e:
            logging.error(f"Failed to process stub {stub_path}: {e}")

    for stem, c_file_path in find_c_extension_modules(package_path, py_stems_seen):
        try:
            rel_dir = os.path.relpath(os.path.dirname(c_file_path), package_path)
            parts = [p for p in rel_dir.split(os.sep) if p and p != '.']
            fqn = f"{package_name}.{'.'.join(parts + [stem])}" if parts else f"{package_name}.{stem}"

            c_labels = ["MODULE", "PYTHON_MODULE", "C_EXTENSION"]
            if version:
                c_labels.append(f"version:{version}")
            c_entity = Entity(
                name=fqn,
                labels=c_labels,
                properties={"__name__": stem, "c_only": True, "file_path": c_file_path},
            )
            c_entity.type = "MODULE"
            all_entities.append(c_entity)
            py_stems_seen.add(stem)
        except Exception as e:
            logging.error(f"Failed to create C-extension placeholder for {c_file_path}: {e}")

    module_entities = {
        e.name: e for e in all_entities
        if "MODULE" in e.labels or "IMPORT_PACKAGE" in e.labels
    }
    existing_structural = {
        (r.from_entity.name, r.to_entity.name, r.label)
        for r in all_relations
        if r.label in {"HAS_SUBMODULE", "HAS_CLASS", "HAS_FUNCTION", "HAS_METHOD", "HAS_VARIABLE"}
    }

    for module_name, module_entity in module_entities.items():
        if "." not in module_name:
            continue
        parent_name = module_name.rsplit('.', 1)[0]
        parent_entity = module_entities.get(parent_name)
        if not parent_entity:
            continue
        key = (parent_entity.name, module_entity.name, "HAS_SUBMODULE")
        if key in existing_structural:
            continue
        all_relations.append(Relationship(parent_entity, module_entity, "HAS_SUBMODULE", {}))
        existing_structural.add(key)
    
    return all_entities, all_relations, all_other_relations, module_symbol_maps
