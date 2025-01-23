"""
ReflEx (Reflection and Extraction) Module

This module provides utilities to extract entities and relationships from Python modules and classes, such as:
- Modules
- Classes
- Methods
- Inheritance
- Imports
"""

from typing import Any, Dict, List, Set, Tuple, Union
import inspect
import importlib

class Entity:
    """
    Module-agnostic entity class.
    """
    def __init__(self, name: str, label: str, properties: Dict):
        self.name = name
        self.label = label
        self.properties = properties
    
    def __repr__(self):
        return f"{self.label} ({self.name})"

class Relationship:
    """
    Module-agnostic relation class.
    """
    def __init__(self, from_entity: Entity, to_entity: Entity, label: str, properties: Dict):
        self.from_entity = from_entity
        self.to_entity = to_entity
        self.label = label
        self.properties = properties
    
    def __repr__(self):
        return f"{self.from_entity} --{self.label}--> {self.to_entity}"

def get_fully_qualified_name(cls):
    """
    Get the fully qualified name of a class.

    Args:
        cls: The class object.

    Returns:
        str: The fully qualified name of the class.
    """
    return f"{cls.__module__}.{cls.__qualname__}"

def check_dunders(path):
    """
    Check if a path starts with an underscore or contains '._'.

    Args:
        path (str): The path to check.

    Returns:
        bool: True if the path starts with an underscore or contains '._', False otherwise.
    """
    return path.startswith("_") or "._" in path

def safe_get_source(obj) -> str:
    """
    Retrieve the source code of an object or fallback to its representation.

    Args:
        obj: The object to retrieve the source code for.

    Returns:
        str: The source code or representation of the object.
    """
    try:
        return inspect.getsource(obj)
    except (OSError, TypeError):
        return f"# Representation:\n{repr(obj)}"

def process_member(
    name: str,
    obj: Any,
    root_module_path: str,
    parent_entity,
    processed_paths: Set[str],
    other_relations: Dict[str, List[Tuple]] = None,
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

    Returns:
        Tuple[List[Entity], List[Relationship]]: List of entities and list of relations.
    """
    entities, relations = [], []

    if name.startswith("_"):
        return [], []

    if inspect.ismodule(obj) or inspect.isclass(obj):
        obj_path = None

        if inspect.ismodule(obj):
            obj_path = obj.__name__
        elif inspect.isclass(obj):
            obj_path = get_fully_qualified_name(obj)

        if not obj_path.startswith(root_module_path):
            if parent_entity:
                other_relations["IMPORTS"].append((parent_entity.name, obj_path))
            return [], []

        if obj_path in processed_paths:
            return [], []

        if check_dunders(obj_path):
            return [], []

        sub_entities, sub_relations = traverse_recursive(
            obj, root_module_path, processed_paths, other_relations
        )
        entities.extend(sub_entities)
        relations.extend(sub_relations)

        relation_type = "HAS_MODULE" if inspect.ismodule(obj) else "HAS_CLASS"
        relations.append(Relationship(parent_entity, entities[0], relation_type, {}))

    elif inspect.isfunction(obj) or inspect.ismethod(obj):
        obj_path = get_fully_qualified_name(obj)

        if check_dunders(obj_path):
            return [], []

        if not obj_path.startswith(root_module_path):
            if parent_entity:
                other_relations["IMPORTS"].append((parent_entity.name, obj_path))
            return [], []

        if obj_path in processed_paths:
            return [], []
        else:
            processed_paths.add(obj_path)

        source_code = safe_get_source(obj)
        method_entity = Entity(
            obj_path, 
            "METHOD", 
            {
                "source": source_code
            }
        )
        entities.append(method_entity)
        if parent_entity:
            relations.append(Relationship(parent_entity, method_entity, "HAS_METHOD", {}))

    return entities, relations

def traverse_recursive(
    obj: Any,
    root_module_path: str,
    processed_paths: Set[str],
    other_relations: Dict[str, List[Tuple]] = None,
) -> Tuple[List[Entity], List[Relationship]]:
    """
    Recursively traverse an object (module or class).

    Args:
        obj (Any): The object to traverse.
        root_module_path (str): The root module path.
        processed_paths (Set[str]): Set of processed paths.
        other_relations (Dict[str, List[Tuple]], optional): Dictionary to store other relations.

    Returns:
        Tuple[List[Entity], List[Relation]]: List of entities and list of relations.
    """
    entities, relations = [], []
    obj_path = None
    entity_type = "MODULE" if inspect.ismodule(obj) else "CLASS"
    if entity_type == "MODULE":
        obj_path = obj.__name__
    elif entity_type == "CLASS":
        obj_path = get_fully_qualified_name(obj)

    if not obj_path.startswith(root_module_path):
        return [], []

    if obj_path in processed_paths:
        return [], []

    else:
        processed_paths.add(obj_path)

    source = safe_get_source(obj)
    properties = {"source": source}

    entity = Entity(obj_path, entity_type, properties)
    entities.append(entity)

    if inspect.isclass(obj):
        for base in obj.__bases__:
            if base.__name__ not in ["object", "type"]:
                base_path = f"{base.__module__}.{base.__name__}"
                other_relations["INHERITS"].append((obj_path, base_path))

    for name, member in inspect.getmembers(obj):
        sub_entities, sub_relations = process_member(
            name, member, root_module_path, entity, processed_paths, other_relations
        )
        entities.extend(sub_entities)
        relations.extend(sub_relations)

    return entities, relations

def process_module(module_name_or_object: Union[str, Any]):
    """
    Process a module or object recursively.

    Args:
        module_name_or_object (Union[str, Any]): Module name or object.

    Returns:
        Tuple[List[Entity], List[Relation], Dict]: List of entities, list of relations, and other relations.
    """
    entities, relations = [], []
    processed_paths = set()
    other_relations = {"INHERITS": [], "IMPORTS": []}

    if isinstance(module_name_or_object, str):
        module_or_object = importlib.import_module(module_name_or_object)

    sub_entities, sub_relations = traverse_recursive(
        module_or_object, module_name_or_object, processed_paths, other_relations
    )
    entities.extend(sub_entities)
    relations.extend(sub_relations)

    print(f"Processed {len(entities)} entities and {len(relations)} relations.")

    return entities, relations, other_relations