"""
ReflEx (Reflection and Extraction) Module

This module provides utilities to extract entities and relationships from Python modules and classes, such as:
- Modules
- Classes
- Methods
- Inheritance
- Imports
"""

from typing import Any, Dict, List, Set, Tuple
import inspect
import importlib
import re
import subprocess
import traceback
import ast
import os
import pkgutil

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

def get_import_statements(source_code: str) -> str:
    """
    Extracts all import statements from the source code, including full
    statements, handling different types, multi-line imports, and 'as' clauses.

    Args:
        source_code (str): The source code of an entity.

    Returns:
        str: All import statements in one clean string block
    """
    try:
      tree = ast.parse(source_code)
      imports = []

      for node in ast.walk(tree):
          if isinstance(node, ast.Import):
              # Handles: import os, sys
              import_statement = "import " + ", ".join(alias.name + (f" as {alias.asname}" if alias.asname else "") for alias in node.names)
              imports.append(import_statement)
          elif isinstance(node, ast.ImportFrom):
              # Handles: from datetime import date, datetime as dt
              names = ", ".join(alias.name + (f" as {alias.asname}" if alias.asname else "") for alias in node.names)
              module = node.module or ''
              level = node.level
              if level > 0:
                module = "." * level + module
              import_statement = f"from {module} import {names}"  #Handles relative imports as well
              imports.append(import_statement)

      return '\n'.join(imports)
    except:
      return ""

def get_import_as_aliases(source_code: str, current_file_path: str) -> List[Tuple[str, str]]:
    """
    Extracts all import ... as ... statements and returns a list of tuples.
    Each tuple contains the full path to the entity and its alias.
    It uses the current_file_path to resolve relative imports to absolute paths.

    Args:
        source_code (str): The source code of an entity.
        current_file_path (str): Full Path of the entity whose source code is being processed

    Returns:
        List[Tuple[str, str]]: List of tuples containing the full path to the entity and its alias.
    """
    try:
      tree = ast.parse(source_code)
      aliases = []

      for node in ast.walk(tree):
          if isinstance(node, ast.Import):
              for alias in node.names:
                  if alias.asname:
                      aliases.append((alias.name, alias.asname))
          elif isinstance(node, ast.ImportFrom):
              module = node.module or ''
              level = node.level
              if level > 0:
                  # Resolve relative import
                  package_path = current_file_path
                  for _ in range(level):
                      package_path = os.path.dirname(package_path)
                      if not package_path:
                          #Reached top level
                          module = "." * level + module
                          break # or raise ValueError("Relative import goes beyond top-level package")

                  if package_path:
                    module = os.path.basename(package_path) + "." + module
                  #If relative import goes beyond current module
                  else:
                    module = "." * level + module
              for alias in node.names:
                  if alias.asname:
                      full_path = f"{module}.{alias.name}" if module else alias.name
                      aliases.append((full_path, alias.asname))
      return aliases
    except:
      return []

def get_unused_imports(module_name: str, imported_names: Set[str]) -> Set[str]:
    """
    Get the list of unused imports in a module using flake8, returning the full paths.

    Args:
        module_name (str): The name of the module.
        imported_names (Set[str]): The set of fully qualified imported names.

    Returns:
        Set[str]: The set of unused imports (full paths).
    """
    try:
        # Get the full file path of the module
        module = importlib.import_module(module_name)
        module_file_path = module.__file__
        print(f"Checking unused imports for {module_name} at {module_file_path}...")

        # Run flake8 and capture output
        process = subprocess.run(
            ["python", "-m", "flake8", "--select", "F401", module_file_path ],
            capture_output=True,
            text=True,
            check=True,
            shell=True,
        )

        output = process.stdout
        unused_names = list()

        # Parse the output for unused import errors (F401), extracting the simple names
        for line in output.splitlines():
            match = re.search(r":\d+:(\d+): F401 '(.*)' imported but unused", line)
            if match:
                unused_names.append(match.group(2))

        # Handle aliases and from-imports statements
        for i in range(len(unused_names)):
            name = unused_names[i].strip()
            if " as " in name:
                unused_names[i] = name.split(" as ")[0]
            if name.startswith("from "):
                unused_names[i] = name.split("from ")[1]
            if " import " in name:
                # Import this unused name to get the fully qualified name
                split_name = name.split(" import ")
                module_name = split_name[0]
                imported_name = split_name[1]
                imported_module = importlib.import_module(module_name)
                imported_entity = getattr(imported_module, imported_name)
                unused_names[i] = get_fully_qualified_name(imported_entity)

        unused_imports = set()
        for full_name in imported_names:
            # if any(name == full_name or full_name.startswith(f"{name}.") for name in unused_names):
            #     unused_imports.add(full_name)
            if any(full_name.endswith(name) for name in unused_names):
                 unused_imports.add(full_name)

        return unused_imports
    except Exception as e:
        print(f"Error getting unused imports for {module_name}: {e}")
        print(traceback.format_exc())
        return set()

def get_fully_qualified_name(cls):
    """
    Get the fully qualified name of a class.

    Args:
        cls: The class object.

    Returns:
        str: The fully qualified name of the class.
    """
    return f"{cls.__module__}.{cls.__qualname__}"

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

    if inspect.ismodule(obj) or inspect.isclass(obj):
        obj_path = None

        if inspect.ismodule(obj):
            obj_path = obj.__name__
        elif inspect.isclass(obj):
            obj_path = get_fully_qualified_name(obj)

        if not obj_path.startswith(root_module_path + "."):
            if parent_entity and parent_entity.label in {"ROOT_MODULE", "MODULE"}:
                other_relations["IMPORTS"].add((parent_entity.name, obj_path))
            return [], []

        if obj_path in processed_paths:
            if parent_entity and parent_entity.label in {"ROOT_MODULE", "MODULE"}:
                other_relations["IMPORTS"].add((parent_entity.name, obj_path))
            return [], []

        if not obj_path.startswith(parent_entity.name + "."):
            if parent_entity and parent_entity.label in {"ROOT_MODULE", "MODULE"}:
                other_relations["IMPORTS"].add((parent_entity.name, obj_path))
            return [], []

        sub_entities, sub_relations = traverse_recursive(
            obj, root_module_path, processed_paths, other_relations
        )
        entities.extend(sub_entities)
        relations.extend(sub_relations)

        relation_type = "HAS_SUBMODULE" if inspect.ismodule(obj) else "HAS_CLASS"
        relations.append(Relationship(parent_entity, entities[0], relation_type, {}))

    elif inspect.isfunction(obj) and parent_entity.label in {"ROOT_MODULE", "MODULE"}:
        obj_path = get_fully_qualified_name(obj)

        if not obj_path.startswith(root_module_path + "."):
            if parent_entity and parent_entity.label in {"ROOT_MODULE", "MODULE"}:
                other_relations["IMPORTS"].add((parent_entity.name, obj_path))
            return [], []

        if obj_path in processed_paths:
            if parent_entity and parent_entity.label in {"ROOT_MODULE", "MODULE"}:
                other_relations["IMPORTS"].add((parent_entity.name, obj_path))
            return [], []

        elif not obj_path.startswith(parent_entity.name + "."):
            if parent_entity and parent_entity.label in {"ROOT_MODULE", "MODULE"}:
                other_relations["IMPORTS"].add((parent_entity.name, obj_path))
            return [], []

        else:
            processed_paths.add(obj_path)

        source_code = safe_get_source(obj)
        function_entity = Entity(
            obj_path,
            "FUNCTION",
            {
                "source": source_code,
                "__name__": obj.__name__,
                "signature": str(inspect.signature(obj))
            }
        )
        entities.append(function_entity)
        if parent_entity:
            relations.append(Relationship(parent_entity, function_entity, "HAS_FUNCTION", {}))

    elif parent_entity.label == "CLASS" and (inspect.ismethod(obj) or inspect.isfunction(obj)):
        obj_path = get_fully_qualified_name(obj)

        if not obj_path.startswith(root_module_path + "."):
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
                "source": source_code,
                "__name__": obj.__name__,
                "signature": str(inspect.signature(obj))
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

    if not obj_path.startswith(root_module_path + "."):
        return [], []

    if obj_path in processed_paths:
        return [], []

    else:
        processed_paths.add(obj_path)

    source = safe_get_source(obj)
    properties = {
        "source": source,
        "__name__": obj.__name__,
    }

    if inspect.ismodule(obj):
        properties["import_statements"] = get_import_statements(source)
        properties["import_as_aliases"] = get_import_as_aliases(source, obj_path)

    entity = Entity(obj_path, entity_type, properties)
    entities.append(entity)

    if inspect.isclass(obj):
        for base in obj.__bases__:
            if base.__name__ not in ["object", "type"]:
                base_path = f"{base.__module__}.{base.__qualname__}"
                # Check if the following fix works
                if base_path == obj_path:
                    continue
                other_relations["INHERITS"].add((obj_path, base_path))

    # Get all sub-modules using `pkgutil` and NOT `inspect` and then process them
    if inspect.ismodule(obj):
        try:
          path = [obj.__path__[0]]
        except:
          try:
            path = [obj.__file__]
          except:
            path = None
        if path:
          submodules = [name for _, name, _ in pkgutil.iter_modules(path)]
          for submodule_name in submodules:
            try:
              submodule_path = f"{obj.__name__}.{submodule_name}"
              sub_entities, sub_relations = process_member(
                  submodule_name,
                  importlib.import_module(submodule_path),
                  root_module_path,
                  entity,
                  processed_paths,
                  other_relations
              )
              entities.extend(sub_entities)
              relations.extend(sub_relations)
            except:
              continue

    # Process sub-classes
    for name, member in inspect.getmembers(obj, inspect.isclass):
        sub_entities, sub_relations = process_member(
            name, member, root_module_path, entity, processed_paths, other_relations
        )
        entities.extend(sub_entities)
        relations.extend(sub_relations)

    # Process functions
    for name, member in inspect.getmembers(obj, inspect.isfunction):
        sub_entities, sub_relations = process_member(
            name, member, root_module_path, entity, processed_paths, other_relations
        )
        entities.extend(sub_entities)
        relations.extend(sub_relations)

    # Process methods
    for name, member in inspect.getmembers(obj, inspect.ismethod):
        sub_entities, sub_relations = process_member(
            name, member, root_module_path, entity, processed_paths, other_relations
        )
        entities.extend(sub_entities)
        relations.extend(sub_relations)

    return entities, relations

def process_module(module_name: str):
    """
    Process a module or object recursively.

    Args:
        module_name (str): Module name or object.

    Returns:
        Tuple[List[Entity], List[Relation], Dict]: List of entities, list of relations, and other relations.
    """
    entities, relations = [], []
    processed_paths = set()
    other_relations = {"INHERITS": set(), "IMPORTS": set(), "EXPOSES": set()}

    module_object = importlib.import_module(module_name)

    source = safe_get_source(module_object)
    all_import_statements = get_import_statements(source)
    import_as_aliases = get_import_as_aliases(source, module_name)
    properties = {
        "source": source,
        "__name__": module_object.__name__,
        "import_statements": all_import_statements,
        "import_as_aliases": import_as_aliases
    }

    root_entity = Entity(module_name, "ROOT_MODULE", properties)
    entities.append(root_entity)

    # Get all sub-modules using `pkgutil` and NOT `inspect` and then process them
    try:
      path = [module_object.__path__[0]]
    except:
      try:
        path = [module_object.__file__]
      except:
        path = None
    if path:
      submodules = [name for _, name, _ in pkgutil.iter_modules(path)]
      for submodule_name in submodules:
        try:
          submodule_path = f"{module_object.__name__}.{submodule_name}"
          sub_entities, sub_relations = process_member(
              submodule_name,
              importlib.import_module(submodule_path),
              module_name,
              root_entity,
              processed_paths,
              other_relations
          )
          entities.extend(sub_entities)
          relations.extend(sub_relations)
        except:
          continue

    # Process sub-classes
    for name, member in inspect.getmembers(module_object, inspect.isclass):
        sub_entities, sub_relations = process_member(
            name, member, module_name, root_entity, processed_paths, other_relations
        )
        entities.extend(sub_entities)
        relations.extend(sub_relations)

    # Process functions
    for name, member in inspect.getmembers(module_object, inspect.isfunction):
        sub_entities, sub_relations = process_member(
            name, member, module_name, root_entity, processed_paths, other_relations
        )
        entities.extend(sub_entities)
        relations.extend(sub_relations)

    # Process methods
    for name, member in inspect.getmembers(module_object, inspect.ismethod):
        sub_entities, sub_relations = process_member(
            name, member, module_name, root_entity, processed_paths, other_relations
        )
        entities.extend(sub_entities)
        relations.extend(sub_relations)

    # Convert IMPORTS to EXPOSES for unused imports
    imported_relations = other_relations["IMPORTS"]
    updated_imported_relations = set()
    module_to_imports = {}

    for from_entity, to_entity in imported_relations:
        full_module_path = from_entity

        if full_module_path not in module_to_imports:
            module_to_imports[full_module_path] = set()

        module_to_imports[full_module_path].add(to_entity)

    for module, imports in module_to_imports.items():
        unused_imports = get_unused_imports(module, imports)
        used_imports = set(imports) - set(unused_imports)

        for unused_import in unused_imports:
            other_relations["EXPOSES"].add((module, unused_import))

        for used_import in used_imports:
            updated_imported_relations.add((module, used_import))

    other_relations["IMPORTS"] = updated_imported_relations

    cleaned_exposed_relations = set()
    cleaned_imports_relations = set()

    # Clean up IMPORTS relations
    for from_entity, to_entity in other_relations["IMPORTS"]:
        to_entity_ancestor_path = ".".join(to_entity.split(".")[:-1])
        if to_entity_ancestor_path == from_entity:
            continue
        elif from_entity == module_name and to_entity.startswith(module_name):
            other_relations["EXPOSES"].add((from_entity, to_entity))
        else:
            cleaned_imports_relations.add((from_entity, to_entity))

    # Clean up EXPOSED relations
    for from_entity, to_entity in other_relations["EXPOSES"]:
        to_entity_ancestor_path = ".".join(to_entity.split(".")[:-1])
        if to_entity_ancestor_path == from_entity:
            continue
        if not to_entity.startswith(from_entity):
            continue
        cleaned_exposed_relations.add((from_entity, to_entity))

    # Deduplicate entities and relations
    entities = list(set(entities))
    relations = list(set(relations))

    # Clean up Alias Imports
    for entity in entities:
        if entity.label not in ("ROOT_MODULE", "MODULE"):
            continue

        cleaned_import_aliases = []
        for key, value in entity.properties["import_as_aliases"]:
            if (entity, key) in other_relations["EXPOSES"] or (entity, key) in other_relations["IMPORTS"]:
                cleaned_import_aliases.append((key, value))

        entity.properties["import_as_aliases"] = cleaned_import_aliases

    other_relations["EXPOSES"] = list(cleaned_exposed_relations)
    other_relations["IMPORTS"] = list(cleaned_imports_relations)
    other_relations["INHERITS"] = list(other_relations["INHERITS"])

    print(f"Processed {len(entities)} entities and {len(relations)} relations in {module_name}.")

    return entities, relations, other_relations