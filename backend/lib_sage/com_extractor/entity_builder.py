"""
Entity and relationship creation utilities.

This module provides utilities for creating property entities, processing callables
with overloads, and extracting import details.
"""

import ast
import inspect
import json
import logging
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from typing_extensions import get_overloads, Literal

from .models import Entity, Relationship
from .source_utils import safe_get_source, safe_get_docstring
from .signature_utils import get_typed_signature, _normalize_signature
from .decorator_utils import get_function_method_labels, _resolve_decorator_details


def _is_dunder(name: str) -> bool:
    """Return True if name is a Python dunder like __init__ (starts and ends with __)."""
    return len(name) >= 4 and name.startswith("__") and name.endswith("__")


def _get_entity_version(entity_path: str) -> Optional[str]:
    """
    Try to determine the version of an external entity by looking at its module's package.
    
    Args:
        entity_path: Fully qualified path like 'numpy.ndarray' or 'pandas.DataFrame'
    
    Returns:
        Version string if found, None otherwise
    """
    try:
        import importlib
        import importlib.metadata
        
        # Extract the root package name (first component)
        root_package = entity_path.split('.')[0]
        
        # Try to get version from importlib.metadata
        try:
            version = importlib.metadata.version(root_package)
            return version
        except importlib.metadata.PackageNotFoundError:
            pass
        
        # Try to get version from __version__ attribute if module is loaded
        try:
            module = importlib.import_module(root_package)
            if hasattr(module, '__version__'):
                return str(module.__version__)
        except Exception:
            pass
        
        return None
    except Exception as e:
        logging.debug(f"Could not determine version for {entity_path}: {e}")
        return None


def _create_property_entity(
    parent_name: str,
    property_type: str,
    value: Any,
    version: Optional[str] = None
) -> Entity:
    """
    Create a property entity (SIGNATURE, SOURCE, DOCSTRING, etc.).
    
    Args:
        parent_name: Full name of the parent entity
        property_type: Type of property (e.g., 'SIGNATURE', 'SOURCE', 'DOCSTRING')
        value: The property value (string or dict for complex types)
        version: Version label if applicable
    
    Returns:
        Entity object for the property
    """
    # Create a unique name for the property entity
    name = f"{parent_name}::{property_type}"
    
    labels = [property_type]
    if version:
        labels.append(f"version:{version}")
    
    # Store value as string (JSON for complex types)
    if isinstance(value, (dict, list)):
        value_str = json.dumps(value, sort_keys=True)
    else:
        value_str = str(value) if value is not None else ""
    
    properties = {"value": value_str}
    
    return Entity(name=name, labels=labels, properties=properties)


def _create_property_entities_and_relations(
    parent_entity: Entity,
    source_code: str,
    docstring: str,
    signature: Optional[str],
    resolved_signature: Optional[str],
    decorators: List[Dict[str, Any]],
    import_details: Optional[Dict],
    version: Optional[str],
) -> Tuple[List[Entity], List[Relationship]]:
    """
    Create property entities and their relationships to a parent entity.
    
    Args:
        parent_entity: The parent entity (METHOD, FUNCTION, CLASS, MODULE, etc.)
        source_code: Source code string
        docstring: Docstring string
        signature: Raw signature string (for METHOD/FUNCTION/CLASS)
        resolved_signature: Type-resolved signature string
        decorators: List of decorator dicts with 'name', 'args', 'resolved_path', 'version'
        import_details: Import details dict (for MODULE/ROOT_MODULE)
        version: Version string
        
    Returns:
        Tuple of (property_entities, property_relationships)
    """
    prop_entities: List[Entity] = []
    prop_relations: List[Relationship] = []
    
    # SOURCE entity
    if source_code:
        source_entity = _create_property_entity(
            parent_entity.name, "SOURCE", source_code, version
        )
        prop_entities.append(source_entity)
        prop_relations.append(
            Relationship(parent_entity, source_entity, "HAS_SOURCE", {})
        )
    
    # DOCSTRING entity
    if docstring:
        docstring_entity = _create_property_entity(
            parent_entity.name, "DOCSTRING", docstring, version
        )
        prop_entities.append(docstring_entity)
        prop_relations.append(
            Relationship(parent_entity, docstring_entity, "HAS_DOCSTRING", {})
        )
    
    # SIGNATURE entity (for METHOD/FUNCTION/CLASS)
    if signature:
        signature_entity = _create_property_entity(
            parent_entity.name, "SIGNATURE", signature, version
        )
        prop_entities.append(signature_entity)
        prop_relations.append(
            Relationship(parent_entity, signature_entity, "HAS_SIGNATURE", {})
        )
    
    # RESOLVED_SIGNATURE entity
    if resolved_signature:
        resolved_sig_entity = _create_property_entity(
            parent_entity.name, "RESOLVED_SIGNATURE", resolved_signature, version
        )
        prop_entities.append(resolved_sig_entity)
        prop_relations.append(
            Relationship(parent_entity, resolved_sig_entity, "HAS_RESOLVED_SIGNATURE", {})
        )
    
    # DECORATOR_DETAILS entity (if decorators exist)
    if decorators:
        decorator_details = {"decorators": decorators}
        decorator_entity = _create_property_entity(
            parent_entity.name, "DECORATOR_DETAILS", decorator_details, version
        )
        prop_entities.append(decorator_entity)
        prop_relations.append(
            Relationship(parent_entity, decorator_entity, "HAS_DECORATOR_DETAILS", {})
        )
    
    # IMPORT_DETAILS entity (for MODULE/ROOT_MODULE)
    if import_details:
        import_entity = _create_property_entity(
            parent_entity.name, "IMPORT_DETAILS", import_details, version
        )
        prop_entities.append(import_entity)
        prop_relations.append(
            Relationship(parent_entity, import_entity, "HAS_IMPORT_DETAILS", {})
        )
    
    return prop_entities, prop_relations


def _process_callable_with_overloads(
    obj: Any,
    name: str,
    obj_path: str,
    entity_type: Literal["FUNCTION", "METHOD"],
    parent_entity: Entity,
    root_module_path: str,
    version: Optional[str],
    parent_obj: Optional[Any] = None,
) -> Tuple[List[Entity], List[Relationship]]:
    """
    Process a callable (function or method) and its overloads, creating property entities.
    
    Args:
        obj: The callable object (function or method)
        name: Name of the callable
        obj_path: Fully qualified path of the callable
        entity_type: Either "FUNCTION" or "METHOD"
        parent_entity: Parent entity (MODULE, ROOT_MODULE, or CLASS)
        root_module_path: Root module path for decorator resolution
        version: Version label if applicable
        parent_obj: Parent object (for decorator resolution)
        
    Returns:
        Tuple of (entities_list, relationships_list)
    """
    entities: List[Entity] = []
    relations: List[Relationship] = []
    
    # Get source, docstring, labels, and decorators
    source_code = safe_get_source(obj)
    docstring = safe_get_docstring(obj)
    extra_labels, decorators = get_function_method_labels(obj, name, parent_obj=parent_obj)
    
    # Overload detection
    overloads: List[Callable] = []
    try:
        overloads = get_overloads(obj) or []
    except Exception:
        overloads = []
    
    # Build labels
    labels = [entity_type] + (extra_labels or [])
    if overloads:
        labels.append("OVERLOADED")
    if _is_dunder(obj.__name__):
        labels.append("DUNDER")
    if version:
        labels.append(f"version:{version}")
    
    # Collect signature variants (normalized to remove memory addresses)
    raw_sig = _normalize_signature(str(inspect.signature(obj)))
    resolved_sig = _normalize_signature(str(get_typed_signature(obj, include_overloads=False)))
    
    # Create main entity with minimal properties
    main_entity = Entity(
        obj_path,
        labels,
        {
            "__name__": obj.__name__,
        }
    )
    entities.append(main_entity)
    
    # Add relationship to parent
    if parent_entity:
        rel_type = "HAS_FUNCTION" if entity_type == "FUNCTION" else "HAS_METHOD"
        relations.append(Relationship(parent_entity, main_entity, rel_type, {}))
    
    # Resolve decorators (partial resolution for now, will be enhanced when MODULE context available)
    resolved_decorators = _resolve_decorator_details(
        decorators, "", [], None, root_module_path
    )
    
    # Create property entities for main callable
    prop_entities, prop_relations = _create_property_entities_and_relations(
        main_entity,
        source_code,
        docstring,
        raw_sig,
        resolved_sig,
        resolved_decorators,
        None,  # No import_details for functions/methods
        version
    )
    entities.extend(prop_entities)
    relations.extend(prop_relations)
    
    # Process overloads
    if overloads:
        for idx, ov in enumerate(overloads, start=1):
            try:
                ov_src = safe_get_source(ov)
            except Exception:
                ov_src = ""
            ov_doc = safe_get_docstring(ov)
            ov_extra_labels, ov_decorators = get_function_method_labels(ov, name, parent_obj=parent_obj)
            
            # Build overload labels
            ov_labels = [entity_type, "OVERLOAD"] + (ov_extra_labels or [])
            if _is_dunder(obj.__name__):
                ov_labels.append("DUNDER")
            if version:
                ov_labels.append(f"version:{version}")
            
            # Get overload signatures (normalized to remove memory addresses)
            if hasattr(ov, "__call__") or inspect.isfunction(ov):
                ov_sig_raw = _normalize_signature(str(inspect.signature(ov)))
            else:
                ov_sig_raw = "<unavailable>"
            try:
                ov_sig_res = _normalize_signature(str(get_typed_signature(ov, include_overloads=False)))
            except Exception:
                ov_sig_res = ov_sig_raw
            
            # Create overload entity with minimal properties
            ov_entity = Entity(
                obj_path,
                ov_labels,
                {
                    "__name__": getattr(ov, "__name__", name),
                },
            )
            entities.append(ov_entity)
            
            # Add relationships
            if parent_entity:
                rel_type = "HAS_FUNCTION" if entity_type == "FUNCTION" else "HAS_METHOD"
                relations.append(Relationship(parent_entity, ov_entity, rel_type, {}))
            
            # Resolve decorators for overload
            ov_resolved_decorators = _resolve_decorator_details(
                ov_decorators, "", [], None, root_module_path
            )
            
            # Create property entities for overload
            ov_prop_entities, ov_prop_relations = _create_property_entities_and_relations(
                ov_entity,
                ov_src,
                ov_doc,
                ov_sig_raw,
                ov_sig_res,
                ov_resolved_decorators,
                None,
                version
            )
            entities.extend(ov_prop_entities)
            relations.extend(ov_prop_relations)
    
    return entities, relations


def _process_import_statements(import_statements: str) -> Tuple[Dict, Set[str]]:
    """
    Process import statements from source code and extract import details.
    
    Returns a dictionary with the following structure:
    {
        "modules": {
            "module_name": {
                "version": "x.y.z" or None,
                "entities": [
                    {"name": "entity_name", "fqn": "module.entity", "alias": "alias_name" or None, "used": True/False},
                    ...
                ]
            },
            ...
        }
    }
    
    Args:
        import_statements (str): String containing all import statements
    
    Returns:
        Tuple[Dict, Set[str]]: Dictionary containing structured import information and set of imported entity FQNs
    """
    import_details = {"modules": {}}
    imported_entities: Set[str] = set()  # Track all imported entity FQNs for unused detection
    
    if not import_statements:
        return import_details, imported_entities
    
    try:
        tree = ast.parse(import_statements)
        
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                # Handle: import module [as alias]
                for alias in node.names:
                    module_name = alias.name
                    
                    # Get version for the module
                    module_version = _get_entity_version(module_name)
                    
                    if module_name not in import_details["modules"]:
                        import_details["modules"][module_name] = {
                            "version": module_version,
                            "entities": []
                        }
                    
                    # For "import module", the module itself is the entity
                    entity_info = {
                        "name": module_name.split(".")[-1],
                        "fqn": module_name,
                        "alias": alias.asname,
                        "used": None  # Will be determined later
                    }
                    import_details["modules"][module_name]["entities"].append(entity_info)
                    imported_entities.add(module_name)
            
            elif isinstance(node, ast.ImportFrom):
                # Handle: from module import entity [as alias]
                if not node.module:
                    continue
                
                module_name = node.module
                
                # Get version for the module (not for each entity)
                module_version = _get_entity_version(module_name)
                
                if module_name not in import_details["modules"]:
                    import_details["modules"][module_name] = {
                        "version": module_version,
                        "entities": []
                    }
                
                # Process each imported entity
                for alias in node.names:
                    entity_name = alias.name
                    entity_fqn = f"{module_name}.{entity_name}"
                    
                    entity_info = {
                        "name": entity_name,
                        "fqn": entity_fqn,
                        "alias": alias.asname,
                        "used": None  # Will be determined later
                    }
                    import_details["modules"][module_name]["entities"].append(entity_info)
                    imported_entities.add(entity_fqn)
    
    except Exception as e:
        logging.warning(f"Error processing import statements: {e}")
    
    return import_details, imported_entities
