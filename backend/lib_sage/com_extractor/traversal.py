"""
Recursive traversal utilities for processing Python modules and classes.

This module provides utilities for recursively traversing Python objects,
processing members, and handling external parent classes.
"""

import importlib
import inspect
import logging
import traceback
from typing_extensions import Any, Dict, List, Optional, Set, Tuple

from .models import Entity, Relationship, ExternalEntityRef
from .utils.general_utils import extract_simple_name
from .utils.source_utils import (
    safe_get_source,
    safe_get_docstring,
    get_import_statements,
    get_import_as_aliases,
    find_submodules_importlib_resources,
    get_fully_qualified_name,
)
from .utils.decorator_utils import _visibility_label, _get_decorators_from_source, _resolve_decorator_details
from .entity_builder import (
    _is_dunder,
    _get_entity_version,
    _create_property_entities_and_relations,
    _process_callable_with_overloads,
    _process_import_statements,
)


def process_member(
    name: str,
    obj: Any,
    root_module_path: str,
    parent_entity: Entity,
    processed_paths: Set[str],
    other_relations: Dict[str, Set[Tuple]] = None,
    *,
    version: Optional[str] = None,
    parent_obj: Optional[Any] = None,
) -> Tuple[List[Entity], List[Relationship]]:
    """
    Process individual members of a class or module.

    Args:
        name (str): Name of the member.
        obj (Any): Member object.
        root_module_path (str): The root module path.
        parent_entity: Parent entity.
        processed_paths (Set[str]): Set of processed paths.
        other_relations (Dict[str, List[Tuple]], optional): Dictionary to store other relations.
        version: Version label if applicable
        parent_obj: Parent object for context

    Returns:
        Tuple[List[Entity], List[Relationship]]: List of entities and list of relations.
    """
    entities: List[Entity] = []
    relations: List[Relationship] = []

    if inspect.ismodule(obj) or inspect.isclass(obj):
        obj_path = None

        if inspect.ismodule(obj):
            obj_path = obj.__name__
        elif inspect.isclass(obj):
            obj_path = get_fully_qualified_name(obj)

        if not obj_path.startswith(root_module_path + "."):
            return [], []

        if obj_path in processed_paths:
            return [], []

        if not obj_path.startswith(parent_entity.name + "."):
            return [], []

        sub_entities, sub_relations = traverse_recursive(
            obj, root_module_path, processed_paths, other_relations, version=version
        )
        entities.extend(sub_entities)
        relations.extend(sub_relations)

        relation_type = "HAS_SUBMODULE" if inspect.ismodule(obj) else "HAS_CLASS"
        if entities:
            relations.append(Relationship(parent_entity, entities[0], relation_type, {}))

    elif inspect.isfunction(obj) and parent_entity.label in {"ROOT_MODULE", "MODULE"}:
        obj_path = get_fully_qualified_name(obj)

        if not obj_path.startswith(root_module_path + "."):
            return [], []

        if obj_path in processed_paths:
            return [], []

        elif not obj_path.startswith(parent_entity.name + "."):
            return [], []

        else:
            processed_paths.add(obj_path)

        # Use helper to process function and its overloads
        func_entities, func_relations = _process_callable_with_overloads(
            obj, name, obj_path, "FUNCTION", parent_entity, root_module_path, version, parent_obj
        )
        entities.extend(func_entities)
        relations.extend(func_relations)

    elif parent_entity.label == "CLASS" and (inspect.ismethod(obj) or inspect.isfunction(obj)):
        obj_path = get_fully_qualified_name(obj)

        if not obj_path.startswith(root_module_path + ".") or not obj_path.startswith(parent_entity.name + "."):
            return [], []

        if obj_path in processed_paths:
            return [], []
        else:
            processed_paths.add(obj_path)

        # Use helper to process method and its overloads
        method_entities, method_relations = _process_callable_with_overloads(
            obj, name, obj_path, "METHOD", parent_entity, root_module_path, version, parent_obj
        )
        entities.extend(method_entities)
        relations.extend(method_relations)

    return entities, relations


def traverse_recursive(
    obj: Any,
    root_module_path: str,
    processed_paths: Set[str],
    other_relations: Dict[str, Set[Tuple]] = None,
    *,
    version: Optional[str] = None,
) -> Tuple[List[Entity], List[Relationship]]:
    """
    Recursively traverse an object (module or class).

    Args:
        obj (Any): The object to traverse.
        root_module_path (str): The root module path.
        processed_paths (Set[str]): Set of processed paths.
        other_relations (Dict[str, List[Tuple]], optional): Dictionary to store other relations.
        version: Version label if applicable

    Returns:
        Tuple[List[Entity], List[Relation]]: List of entities and list of relations.
    """
    entities: List[Entity] = []
    relations: List[Relationship] = []
    obj_path = None
    entity_type = "MODULE" if inspect.ismodule(obj) else "CLASS"
    if entity_type == "MODULE":
        obj_path = obj.__name__
    elif entity_type == "CLASS":
        obj_path = get_fully_qualified_name(obj)

    if not obj_path.startswith(root_module_path + "."):
        return [], []

    if obj_path in processed_paths:
        return [], []

    else:
        processed_paths.add(obj_path)

    source = safe_get_source(obj)
    docstring = safe_get_docstring(obj)
    
    # Build labels
    labels = [entity_type]
    if version:
        labels.append(f"version:{version}")
    if entity_type == "CLASS":
        labels.append(_visibility_label(obj.__name__))
        if _is_dunder(obj.__name__):
            labels.append("DUNDER")

    # Create main entity with minimal properties
    entity = Entity(obj_path, labels, {"__name__": extract_simple_name(obj.__name__)})
    entities.append(entity)
    
    # Prepare import_details for MODULE entities
    import_details = None
    if inspect.ismodule(obj):
        import_statements = get_import_statements(source)
        import_as_aliases = get_import_as_aliases(source, obj_path)
        # Process import statements with full context to get EXPOSES/PUBLISHES relationships
        exported_names = getattr(obj, "__all__", None)
        import_details, _, relations = _process_import_statements(
            import_statements,
            entity_name=obj_path,
            entity_content_hash=entity.content_hash,
            root_module_name=root_module_path,
            exported_names=exported_names
        )
        # Store import_statements and aliases for decorator resolution (temporary, will be in property entity)
        entity.properties["import_statements"] = import_statements
        entity.properties["import_as_aliases"] = import_as_aliases
        
        # Add EXPOSES and PUBLISHES relationships to other_relations
        if other_relations is not None:
            other_relations["EXPOSES"].update(relations["EXPOSES"])
            other_relations["PUBLISHES"].update(relations["PUBLISHES"])
            other_relations["EXPOSES_ALL"].update(relations["EXPOSES_ALL"])
            other_relations["PUBLISHES_ALL"].update(relations["PUBLISHES_ALL"])
    
    # For CLASS entities, get decorators
    decorators = []
    if entity_type == "CLASS":
        # Extract decorators from source
        decorators = _get_decorators_from_source(source)
    
    # Resolve decorators (will need parent's import context for proper resolution)
    resolved_decorators = []
    if decorators:
        # For now, pass empty context - will be enhanced when we propagate import context
        resolved_decorators = _resolve_decorator_details(
            decorators, "", [], None, root_module_path
        )
    
    # Create property entities
    prop_entities, prop_relations = _create_property_entities_and_relations(
        entity,
        source,
        docstring,
        None,
        None,
        resolved_decorators,  # Only for CLASS
        import_details,  # Only for MODULE
        version,
        obj  # Pass the source object for line number extraction
    )
    entities.extend(prop_entities)
    relations.extend(prop_relations)

    if inspect.isclass(obj):
        for base in obj.__bases__:
            if base.__name__ not in ["object", "type"]:
                try:
                    base_path = f"{base.__module__}.{base.__qualname__}"
                    if base_path != obj_path:
                        # Try to detect version for external entities
                        base_version = _get_entity_version(base_path) if not base_path.startswith(root_module_path + ".") else version
                        # Create ExternalEntityRef for the base class
                        base_ref = ExternalEntityRef(name=base_path, version=base_version)
                        # Store as (child_content_hash, ExternalEntityRef)
                        # Determine internal vs external inheritance
                        if base_path.startswith(root_module_path + "."):
                            other_relations["INTERNAL_INHERITS"].add((entity.content_hash, base_ref))
                        else:
                            other_relations["EXTERNAL_INHERITS"].add((entity.content_hash, base_ref))
                except Exception:
                    pass

    # Get all sub-modules using `find_submodules_importlib_resources` and process them, if the object is a module
    if inspect.ismodule(obj):
        submodules: set = find_submodules_importlib_resources(obj_path)
        for submodule_path in submodules:
            try:
                submodule_name = submodule_path.split(".")[-1]
                sub_entities, sub_relations = process_member(
                    submodule_name,
                    importlib.import_module(submodule_path),
                    root_module_path,
                    entity,
                    processed_paths,
                    other_relations,
                    version=version,
                    parent_obj=obj,
                )
                entities.extend(sub_entities)
                relations.extend(sub_relations)
            except ModuleNotFoundError as e:
                # If the missing module is external to the root, skip quietly
                missing = getattr(e, 'name', '') or ''
                if missing and not missing.startswith(root_module_path):
                    continue
                logging.error(f"Error processing submodule {submodule_path}: {e}")
                logging.error(traceback.format_exc())
                continue
            except Exception as e:
                logging.error(f"Error processing submodule {submodule_path}: {e}")
                logging.error(traceback.format_exc())
                continue

    # Process sub-classes
    for name, member in inspect.getmembers(obj, inspect.isclass):
        sub_entities, sub_relations = process_member(
            name, member, root_module_path, entity, processed_paths, other_relations, version=version, parent_obj=obj
        )
        entities.extend(sub_entities)
        relations.extend(sub_relations)

    # Process functions
    for name, member in inspect.getmembers(obj, inspect.isfunction):
        sub_entities, sub_relations = process_member(
            name, member, root_module_path, entity, processed_paths, other_relations, version=version, parent_obj=obj
        )
        entities.extend(sub_entities)
        relations.extend(sub_relations)

    # Process methods
    for name, member in inspect.getmembers(obj, inspect.ismethod):
        sub_entities, sub_relations = process_member(
            name, member, root_module_path, entity, processed_paths, other_relations, version=version, parent_obj=obj
        )
        entities.extend(sub_entities)
        relations.extend(sub_relations)

    # Clean up temporary import properties used for decorator resolution
    if "import_statements" in entity.properties:
        del entity.properties["import_statements"]
    if "import_as_aliases" in entity.properties:
        del entity.properties["import_as_aliases"]

    return entities, relations


def _process_single_external_class(
    class_fqn: str,
    version: Optional[str],
    root_module_name: str,
    processed_classes: Set[str]
) -> Tuple[List[Entity], List[Relationship], Dict[str, Set[Tuple]]]:
    """
    Process a single external class and its members (methods, subclasses).
    Does not process the entire module tree.
    
    Args:
        class_fqn (str): Fully qualified name of the class (e.g., "pydantic.BaseModel")
        version (Optional[str]): Version of the class's module
        root_module_name (str): Root module name to avoid processing internal classes
        processed_classes (Set[str]): Set of already processed class FQNs to avoid cycles
    
    Returns:
        Tuple of (entities, relations, other_relations) for the class and its members
    """
    entities: List[Entity] = []
    relations: List[Relationship] = []
    other_relations: Dict[str, Set[Tuple]] = {
        "INTERNAL_INHERITS": set(), 
        "EXTERNAL_INHERITS": set(), 
        "EXPOSES": set(), 
        "PUBLISHES": set(),
        "EXPOSES_ALL": set(),
        "PUBLISHES_ALL": set()
    }
    
    # Skip if already processed
    class_key = f"{class_fqn}@{version}" if version else class_fqn
    if class_key in processed_classes:
        return entities, relations, other_relations
    
    processed_classes.add(class_key)
    
    # Skip if it's from the current root module
    if class_fqn.startswith(root_module_name + "."):
        return entities, relations, other_relations
    
    logging.info(f"Processing external class: {class_fqn} (version: {version or 'latest'})")
    
    try:
        # Import the module containing the class
        module_name = ".".join(class_fqn.split(".")[:-1])
        class_name = class_fqn.split(".")[-1]
        
        try:
            module = importlib.import_module(module_name)
        except ImportError as e:
            logging.warning(f"Could not import module {module_name} for class {class_fqn}: {e}")
            return entities, relations, other_relations
        
        # Get the class object
        if not hasattr(module, class_name):
            logging.warning(f"Class {class_name} not found in module {module_name}")
            return entities, relations, other_relations
        
        cls = getattr(module, class_name)
        
        if not inspect.isclass(cls):
            logging.warning(f"{class_fqn} is not a class")
            return entities, relations, other_relations
        
        # Process the class using traverse_recursive (which handles CLASS entities)
        processed_paths: Set[str] = set()
        class_entities, class_relations = traverse_recursive(
            cls,
            class_fqn.split('.')[0],  # Use the class's root module as root_module_path
            processed_paths,
            other_relations,
            version=version
        )
        
        entities.extend(class_entities)
        relations.extend(class_relations)
        
        logging.info(f"Extracted {len(class_entities)} entities from external class {class_fqn}")
        
    except Exception as e:
        logging.error(f"Error processing external class {class_fqn}: {e}")
        logging.error(traceback.format_exc())
    
    return entities, relations, other_relations


def _process_external_parent_classes(
    inherits_relations: Set[Tuple],
    processed_external_classes: Set[str],
    current_module_name: str,
    all_other_relations: Optional[Dict[str, Set[Tuple]]] = None
) -> Tuple[List[Entity], List[Relationship]]:
    """
    Recursively process external parent classes from INHERITS relationships.
    Only processes the specific classes and their members, not entire modules.
    
    Args:
        inherits_relations (Set[Tuple]): Set of (child_name, ExternalEntityRef) tuples
        processed_external_classes (Set[str]): Set of already processed external class keys
        current_module_name (str): Name of the current module being processed
        all_other_relations (Optional[Dict[str, Set[Tuple]]]): Accumulator for INHERITS/EXPOSES/PUBLISHES from external classes
    
    Returns:
        Tuple of (entities, relations) for all external parent classes
    """
    all_external_entities: List[Entity] = []
    all_external_relations: List[Relationship] = []
    
    # Extract unique external parent classes
    external_classes_to_process: List[Tuple[str, Optional[str]]] = []
    
    for _, parent_ref in inherits_relations:
        if not isinstance(parent_ref, ExternalEntityRef):
            continue
        
        # Get the parent class FQN
        parent_fqn = parent_ref.name
        parent_root_module = parent_fqn.split('.')[0]
        
        # Skip if it's the same module we're currently processing
        if parent_root_module == current_module_name.split('.')[0]:
            continue
        
        parent_version = parent_ref.version
        class_key = f"{parent_fqn}@{parent_version}" if parent_version else parent_fqn
        
        # Skip if already processed
        if class_key in processed_external_classes:
            continue
        
        external_classes_to_process.append((parent_fqn, parent_version))
    
    # Process each external parent class
    for ext_class_fqn, ext_version in external_classes_to_process:
        ext_entities, ext_relations, ext_other_relations = _process_single_external_class(
            ext_class_fqn,
            ext_version,
            current_module_name.split('.')[0],
            processed_external_classes
        )
        
        all_external_entities.extend(ext_entities)
        all_external_relations.extend(ext_relations)
        
        # Accumulate other_relations from external classes if accumulator provided
        if all_other_relations is not None:
            for rel_type in ["INTERNAL_INHERITS", "EXTERNAL_INHERITS", "EXPOSES", "PUBLISHES"]:
                if rel_type in ext_other_relations:
                    all_other_relations[rel_type].update(ext_other_relations[rel_type])
        
        # Recursively process any parent classes that this external class inherits from
        combined_inherits = ext_other_relations["INTERNAL_INHERITS"].union(ext_other_relations["EXTERNAL_INHERITS"])
        
        if combined_inherits:
            recursive_entities, recursive_relations = _process_external_parent_classes(
                combined_inherits,
                processed_external_classes,
                current_module_name,
                all_other_relations  # Pass accumulator through recursion
            )
            all_external_entities.extend(recursive_entities)
            all_external_relations.extend(recursive_relations)
    
    return all_external_entities, all_external_relations
