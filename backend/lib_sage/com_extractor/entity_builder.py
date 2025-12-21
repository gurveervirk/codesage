"""
Entity and relationship creation utilities.

This module provides utilities for creating property entities, processing callables
with overloads, and extracting import details.
"""

import ast
import inspect
import json
import logging
from typing_extensions import Any, Callable, Dict, List, Optional, Set, Tuple
from typing_extensions import Literal

from .models import Entity, Relationship
from .utils.general_utils import extract_simple_name
from .utils.source_utils import safe_get_source, safe_get_docstring, get_source_line_numbers
from .utils.signature_utils import get_typed_signature, _normalize_signature
from .utils.decorator_utils import get_function_method_labels, _resolve_decorator_details
from .utils.overload_utils import get_overloads_with_fallback


def _is_dunder(name: str) -> bool:
    """Return True if name is a Python dunder like __init__ (starts and ends with __)."""
    return len(name) >= 4 and name.startswith("__") and name.endswith("__")


def _extract_raw_signature(obj: Any) -> Optional[str]:
    """
    Extract the raw signature notation from source code using AST.
    
    This extracts the actual signature as written in the source code,
    preserving the original formatting and type hints.
    
    Args:
        obj: The callable object (function, method, or class)
        
    Returns:
        Raw signature string as written in source, or None if unavailable
    """
    try:
        source = safe_get_source(obj)
        if not source or source.startswith("# Representation:"):
            return None
        
        # Parse the source code
        tree = ast.parse(source)
        
        # Find the function/class definition
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                # Extract the signature from the AST node
                if isinstance(node, ast.ClassDef):
                    # For classes, look for __init__ method
                    for item in node.body:
                        if isinstance(item, ast.FunctionDef) and item.name == "__init__":
                            return _build_signature_from_ast(item)
                    # If no __init__, return empty signature
                    return "()"
                else:
                    # For functions/methods
                    return _build_signature_from_ast(node)
        
        return None
    except Exception as e:
        logging.debug(f"Error extracting raw signature: {e}")
        return None


def _build_signature_from_ast(node: ast.FunctionDef) -> str:
    """
    Build signature string from AST FunctionDef node.
    
    Args:
        node: AST FunctionDef or AsyncFunctionDef node
        
    Returns:
        Signature string in format: (arg1: type1, arg2: type2 = default, ...) -> return_type
    """
    args = node.args
    params = []
    
    # Helper to unparse annotation
    def unparse_annotation(annotation):
        if annotation is None:
            return ""
        try:
            return ast.unparse(annotation)
        except Exception:
            return ""
    
    # Helper to unparse default
    def unparse_default(default):
        if default is None:
            return None
        try:
            return ast.unparse(default)
        except Exception:
            return "..."
    
    # Regular positional/keyword arguments
    defaults_offset = len(args.args) - len(args.defaults)
    for i, arg in enumerate(args.args):
        param = arg.arg
        if arg.annotation:
            param += f": {unparse_annotation(arg.annotation)}"
        
        # Check if this arg has a default
        default_idx = i - defaults_offset
        if default_idx >= 0:
            default_val = unparse_default(args.defaults[default_idx])
            if default_val:
                param += f" = {default_val}"
        
        params.append(param)
    
    # *args
    if args.vararg:
        param = f"*{args.vararg.arg}"
        if args.vararg.annotation:
            param += f": {unparse_annotation(args.vararg.annotation)}"
        params.append(param)
    
    # Keyword-only arguments
    for i, arg in enumerate(args.kwonlyargs):
        param = arg.arg
        if arg.annotation:
            param += f": {unparse_annotation(arg.annotation)}"
        
        if i < len(args.kw_defaults) and args.kw_defaults[i] is not None:
            default_val = unparse_default(args.kw_defaults[i])
            if default_val:
                param += f" = {default_val}"
        
        params.append(param)
    
    # **kwargs
    if args.kwarg:
        param = f"**{args.kwarg.arg}"
        if args.kwarg.annotation:
            param += f": {unparse_annotation(args.kwarg.annotation)}"
        params.append(param)
    
    # Build the signature
    sig = f"({', '.join(params)})"
    
    # Add return annotation if present
    if node.returns:
        return_type = unparse_annotation(node.returns)
        if return_type:
            sig += f" -> {return_type}"
    
    return sig


def _get_entity_version(entity_path: str) -> Optional[str]:
    """
    Try to determine the version of an external entity by looking at its module's package.
    
    Handles special cases:
    - Private modules (e.g., _tqdm): Falls back to public module version (tqdm)
    - Python builtins (e.g., os, sys): Returns Python version as py:X.Y.Z
    
    Args:
        entity_path: Fully qualified path like 'numpy.ndarray' or 'pandas.DataFrame'
    
    Returns:
        Version string if found, None otherwise
    """
    try:
        import importlib
        import importlib.metadata
        import sys
        
        # Extract the root package name (first component)
        root_package = entity_path.split('.')[0]
        
        # Check if it's a Python builtin module
        if root_package in sys.builtin_module_names:
            # Return Python version for builtins
            py_version = sys.version_info
            return f"py:{py_version.major}.{py_version.minor}.{py_version.micro}"
        
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
        
        # Special handling for private modules (e.g., _tqdm -> tqdm)
        if root_package.startswith('_'):
            public_package = root_package[1:]  # Remove leading underscore
            try:
                # Try to get version from the public package
                public_version = importlib.metadata.version(public_package)
                return public_version
            except importlib.metadata.PackageNotFoundError:
                pass
            
            # Try __version__ from public package
            try:
                public_module = importlib.import_module(public_package)
                if hasattr(public_module, '__version__'):
                    return str(public_module.__version__)
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
    source_obj: Optional[Any] = None,
) -> Tuple[List[Entity], List[Relationship]]:
    """
    Create property entities and their relationships to a parent entity.
    
    Args:
        parent_entity: The parent entity (METHOD, FUNCTION, CLASS, MODULE, etc.)
        source_code: Source code string (used for MODULE/ROOT_MODULE only)
        docstring: Docstring string
        signature: Raw signature string (for METHOD/FUNCTION/CLASS)
        resolved_signature: Type-resolved signature string
        decorators: List of decorator dicts with 'name', 'args', 'resolved_path', 'version'
        import_details: Import details dict (for MODULE/ROOT_MODULE)
        version: Optional[str],
        source_obj: The source object for line number extraction (required for non-module entities)
        
    Returns:
        Tuple of (property_entities, property_relationships)
    """
    prop_entities: List[Entity] = []
    prop_relations: List[Relationship] = []
    
    # Determine if this is a module entity (should store full source)
    is_module = "MODULE" in parent_entity.labels or "ROOT_MODULE" in parent_entity.labels
    
    # SOURCE entity
    if (is_module and source_code) or (not is_module and (docstring or signature)):
        # Create SOURCE entity name
        name = f"{parent_entity.name}::SOURCE"
        
        labels = ["SOURCE"]
        if version:
            labels.append(f"version:{version}")
        
        # For MODULE/ROOT_MODULE: store full source code
        # For other entities: store line numbers instead
        properties = {}
        
        if is_module:
            # Store full source for modules
            if source_code:
                properties["code"] = source_code
            if docstring:
                properties["docstring"] = docstring
            if signature:
                properties["signature"] = signature
        else:
            # Store line numbers for non-module entities
            if source_obj:
                line_info = get_source_line_numbers(source_obj)
                if line_info:
                    properties["line_start"] = str(line_info[0])
                    properties["line_end"] = str(line_info[1])
            if docstring:
                properties["docstring"] = docstring
            if signature:
                properties["signature"] = signature
        
        source_entity = Entity(name=name, labels=labels, properties=properties)
        prop_entities.append(source_entity)
        prop_relations.append(
            Relationship(parent_entity, source_entity, "HAS_SOURCE", {})
        )
    
    # RESOLVED_SIGNATURE entity - kept separate as it's derived from type analysis
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
    extra_labels, decorators = get_function_method_labels(obj, name)
    
    # Overload detection
    overloads: List[Callable] = []
    try:
        overloads = get_overloads_with_fallback(obj) or []
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
    
    # Collect signature variants
    # raw_sig: Extract actual signature from source using AST
    raw_sig = _extract_raw_signature(obj)
    if not raw_sig:
        # Fallback to inspect.signature if AST extraction fails
        raw_sig = _normalize_signature(str(inspect.signature(obj)))
    
    # resolved_sig: Type-resolved signature (normalized to remove memory addresses)
    resolved_sig = _normalize_signature(str(get_typed_signature(obj, include_overloads=False)))
    
    # Create main entity with minimal properties
    main_entity = Entity(
        obj_path,
        labels,
        {
            "__name__": extract_simple_name(obj.__name__),
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
        version,
        obj  # Pass the source object for line number extraction
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
            ov_extra_labels, ov_decorators = get_function_method_labels(ov, name)
            
            # Build overload labels
            ov_labels = [entity_type, "OVERLOAD"] + (ov_extra_labels or [])
            if _is_dunder(obj.__name__):
                ov_labels.append("DUNDER")
            if version:
                ov_labels.append(f"version:{version}")
            
            # Get overload signatures
            # ov_sig_raw: Extract actual signature from source using AST
            ov_sig_raw = _extract_raw_signature(ov)
            if not ov_sig_raw:
                # Fallback to inspect.signature if AST extraction fails
                if hasattr(ov, "__call__") or inspect.isfunction(ov):
                    ov_sig_raw = _normalize_signature(str(inspect.signature(ov)))
                else:
                    ov_sig_raw = "<unavailable>"
            
            # ov_sig_res: Type-resolved signature
            try:
                ov_sig_res = _normalize_signature(str(get_typed_signature(ov, include_overloads=False)))
            except Exception:
                ov_sig_res = ov_sig_raw
            
            # Create overload entity with minimal properties
            ov_entity = Entity(
                obj_path,
                ov_labels,
                {
                    "__name__": extract_simple_name(getattr(ov, "__name__", name)),
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
                version,
                ov  # Pass the overload object for line number extraction
            )
            entities.extend(ov_prop_entities)
            relations.extend(ov_prop_relations)
    
    return entities, relations


def _process_import_statements(
    import_statements: str,
    entity_name: Optional[str] = None,
    entity_content_hash: Optional[str] = None,
    root_module_name: Optional[str] = None
) -> Tuple[Dict, Set[str], Set[Tuple], Set[Tuple]]:
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
        import_statements: String containing all import statements
        entity_name: The name of the entity (module/ROOT_MODULE) being processed
        entity_content_hash: The content_hash of the entity for relationship tracking
        root_module_name: The root module name to determine internal vs external imports
    
    Returns:
        Tuple containing:
        - Dict: Structured import information
        - Set[str]: Set of imported entity FQNs
        - Set[Tuple]: EXPOSES relationships (entity_hash, ExternalEntityRef)
        - Set[Tuple]: PUBLISHES relationships (entity_hash, ExternalEntityRef)
    """
    from .models import ExternalEntityRef
    from .utils.source_utils import get_unused_imports
    
    import_details = {"modules": {}}
    imported_entities: Set[str] = set()  # Track all imported entity FQNs for unused detection
    exposes_relations: Set[Tuple] = set()
    publishes_relations: Set[Tuple] = set()
    
    if not import_statements:
        return import_details, imported_entities, exposes_relations, publishes_relations
    
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
                    imported_entity_name = alias.name
                    
                    # Try to determine the actual FQN by importing the entity
                    entity_fqn = f"{module_name}.{imported_entity_name}"
                    try:
                        import importlib
                        imported_module = importlib.import_module(module_name)
                        if hasattr(imported_module, imported_entity_name):
                            imported_obj = getattr(imported_module, imported_entity_name)
                            # Try to get the actual module where the object is defined
                            if hasattr(imported_obj, '__module__'):
                                actual_module = imported_obj.__module__
                                if hasattr(imported_obj, '__qualname__'):
                                    entity_fqn = f"{actual_module}.{imported_obj.__qualname__}"
                                else:
                                    entity_fqn = f"{actual_module}.{imported_entity_name}"
                    except Exception as e:
                        logging.debug(f"Could not resolve actual FQN for {module_name}.{imported_entity_name}: {e}")
                    
                    entity_info = {
                        "name": imported_entity_name,
                        "fqn": entity_fqn,
                        "alias": alias.asname,
                        "used": None  # Will be determined later
                    }
                    import_details["modules"][module_name]["entities"].append(entity_info)
                    imported_entities.add(entity_fqn)
    
    except Exception as e:
        logging.warning(f"Error processing import statements: {e}")
    
    # Determine unused imports and create EXPOSES/PUBLISHES relationships
    if entity_name and entity_content_hash and root_module_name and imported_entities:
        try:
            # Convert to frozenset for caching (lru_cache requires hashable args)
            unused_imports = get_unused_imports(entity_name, frozenset(imported_entities))
            logging.debug(f"Entity {entity_name} has {len(unused_imports)} unused imports out of {len(imported_entities)} imported entities.")
            
            # Update the "used" status in import_details and create relationships
            for module_name, module_info in import_details["modules"].items():
                for entity_info in module_info["entities"]:
                    entity_fqn = entity_info["fqn"]
                    if entity_fqn in unused_imports:
                        entity_info["used"] = False
                        entity_info["import_statement"] = unused_imports[entity_fqn]
                        
                        # Determine relationship type
                        import_version = module_info["version"]
                        import_ref = ExternalEntityRef(name=entity_fqn, version=import_version)
                        
                        # Check for _<package> pattern (PUBLISHES)
                        from_root = entity_name.split(".")[0]
                        to_root = entity_fqn.split(".")[0]
                        
                        is_publishes = False
                        if from_root.startswith("_") and to_root == from_root[1:]:
                            # Case: _pytest publishing to pytest
                            is_publishes = True
                        elif to_root.startswith("_") and from_root == to_root[1:]:
                            # Case: pytest publishing from _pytest
                            is_publishes = True
                        
                        if is_publishes:
                            publishes_relations.add((entity_content_hash, import_ref))
                        elif entity_fqn.startswith(root_module_name + "."):
                            # Internal import that's unused -> EXPOSES
                            exposes_relations.add((entity_content_hash, import_ref))
                        else:
                            # External unused import -> PUBLISHES
                            publishes_relations.add((entity_content_hash, import_ref))
                    else:
                        entity_info["used"] = True
        except Exception as e:
            logging.warning(f"Error determining unused imports for {entity_name}: {e}")
    
    return import_details, imported_entities, exposes_relations, publishes_relations
