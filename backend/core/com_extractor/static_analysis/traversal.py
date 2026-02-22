"""
Static filesystem traversal for package extraction.
"""

import os
import logging
from typing import List, Tuple, Generator, Dict, Any

from ..models import Entity, Relationship
from .parsers.python_parser import PythonTreeSitterParser
from .builder import convert_module

def find_python_files(root_path: str) -> Generator[str, None, None]:
    """Yield all .py files in the directory or the file itself."""
    if os.path.isfile(root_path) and root_path.endswith('.py'):
        yield root_path
        return

    for root, _, files in os.walk(root_path):
        for file in files:
            if file.endswith('.py'):
                yield os.path.join(root, file)

def get_module_fqn(file_path: str, root_path: str, package_name: str) -> str:
    """
    Calculate Fully Qualified Name from file path relative to root.
    Example: root/sub/mod.py -> package_name.sub.mod
    """
    rel_path = os.path.relpath(file_path, root_path)
    # Remove .py
    path_no_ext = os.path.splitext(rel_path)[0]
    
    # Handle __init__
    if path_no_ext.endswith('__init__'):
         path_no_ext = os.path.dirname(path_no_ext)
         if not path_no_ext:
             return package_name
    
    if path_no_ext == '.':
        return package_name
        
    parts = path_no_ext.split(os.sep)
    # Filter empty parts just in case
    parts = [p for p in parts if p]
    
    if not parts:
        return package_name
        
    return f"{package_name}.{'.'.join(parts)}"

def process_package_static(
    package_path: str, 
    package_name: str, 
    version: str,
    parser: PythonTreeSitterParser = None
) -> Tuple[List[Entity], List[Relationship], Dict[str, Any]]:
    """
    Process a package directory statically.
    """
    if parser is None:
        parser = PythonTreeSitterParser()
        
    all_entities = []
    all_relations = []
    all_other_relations = {}
    
    logging.info(f"Starting static extraction for {package_name} at {package_path}")
    
    # Create top-level package entity reference if needed?
    # Usually the __init__.py at root will create the module entity corresponding to package_name.
    
    # Determine base directory for relative path calculation
    # We want paths like 'package/module.py', so we go one level up from the package root
    base_dir = os.path.dirname(package_path)
    
    for file_path in find_python_files(package_path):
        try:
            fqn = get_module_fqn(file_path, package_path, package_name)
            
            # Parse
            parsed_data = parser.parse_file(file_path)
            
            # Inject relative path
            # User Preference: Split by site-packages if available
            if "site-packages" in file_path:
                # Take the part after the last site-packages
                rel_path = file_path.split("site-packages")[-1]
                # Remove leading slash (os specific)
                rel_path = rel_path.lstrip(os.sep)
                parsed_data['file_path'] = rel_path
            else:
                try:
                    rel_path = os.path.relpath(file_path, base_dir)
                    parsed_data['file_path'] = rel_path
                except ValueError:
                    # Fallback if paths are on different drives/invalid relative
                    pass

            # Convert
            entities, relations, other_rels = convert_module(
                parsed_data, 
                fqn, 
                version
            )
            for k, v in other_rels.items():
                if k not in all_other_relations:
                    all_other_relations[k] = []
                all_other_relations[k].extend(v)
            
            all_entities.extend(entities)
            all_relations.extend(relations)
            
        except Exception as e:
            logging.error(f"Failed to process {file_path}: {e}")
            import traceback
            traceback.print_exc()

    module_entities = {
        e.name: e for e in all_entities
        if "MODULE" in e.labels or "IMPORT_PACKAGE" in e.labels
    }
    existing_structural = {
        (r.from_entity.name, r.to_entity.name, r.label)
        for r in all_relations
        if r.label in {"HAS_SUBMODULE", "HAS_CLASS", "HAS_FUNCTION", "HAS_METHOD"}
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
    
    return all_entities, all_relations, all_other_relations