"""
Module processing and orchestration.

This module provides the core process_module function that orchestrates
the extraction of entities and relationships from Python modules.
"""

import importlib
import inspect
import logging
import traceback
from typing_extensions import Dict, List, Optional, Set, Tuple

from .models import Entity, Relationship, ExternalEntityRef
from .source_utils import (
    safe_get_source,
    safe_get_docstring,
    get_import_statements,
    get_import_as_aliases,
    find_submodules_importlib_resources,
)
from .entity_builder import _create_property_entities_and_relations, _process_import_statements
from .traversal import process_member, _process_external_parent_classes


def _parse_name_and_version(name_or_spec: str, explicit_version: Optional[str] = None) -> Tuple[str, Optional[str]]:
    """
    Parse a module/package spec possibly containing a version (e.g., "pkg==1.2.3" or "pkg@1.2.3").

    Returns (name, version) where version may be None if not present and not provided explicitly.
    """
    if explicit_version:
        # Strip any inline version from name_or_spec if explicit version provided
        base = name_or_spec.split("@")[0].split("==")[0]
        return base, explicit_version
    for sep in ("==", "@"):  # simple parsing for now
        if sep in name_or_spec:
            name, ver = name_or_spec.split(sep, 1)
            return name.strip(), (ver.strip() or None)
    return name_or_spec, None


def process_module(
    module_name: str,
    version: Optional[str] = None,
    include_external_parents: bool = True,
    _processed_external_classes: Optional[Set[str]] = None
) -> Tuple[List[Entity], List[Relationship], Dict]:
    """
    Process a module or object recursively.

    Args:
        module_name (str): Module name or object.
        version (Optional[str]): Version of the module.
        include_external_parents (bool): Whether to recursively process external parent classes.
        _processed_external_classes (Optional[Set[str]]): Internal tracking of processed external classes to avoid cycles.

    Returns:
        Tuple[List[Entity], List[Relation], Dict]: List of entities, list of relations, and other relations.
    """
    name_only, parsed_version = _parse_name_and_version(module_name, version)
    version = parsed_version

    # Initialize tracking set for external classes if not provided (top-level call)
    if _processed_external_classes is None:
        _processed_external_classes = set()

    entities: List[Entity] = []
    relations: List[Relationship] = []
    processed_paths: Set[str] = set()
    other_relations: Dict[str, Set[Tuple]] = {"INHERITS": set(), "EXPOSES": set(), "PUBLISHES": set()}

    module_object = importlib.import_module(name_only)

    source = safe_get_source(module_object)
    docstring = safe_get_docstring(module_object)
    all_import_statements = get_import_statements(source)
    import_as_aliases = get_import_as_aliases(source, module_object.__name__)
    
    labels = ["ROOT_MODULE"]
    if version:
        labels.append(f"version:{version}")
    
    # Create main entity with minimal properties
    root_entity = Entity(module_object.__name__, labels, {"__name__": module_object.__name__})
    
    # Store import info temporarily for decorator resolution (will be removed after children are processed)
    root_entity.properties["import_statements"] = all_import_statements
    root_entity.properties["import_as_aliases"] = import_as_aliases
    
    entities.append(root_entity)
    
    # Process import statements with full context to get EXPOSES/PUBLISHES relationships for ROOT_MODULE
    import_details, _, exposes_rels, publishes_rels = _process_import_statements(
        all_import_statements,
        entity_name=module_object.__name__,
        entity_content_hash=root_entity.content_hash,
        root_module_name=module_object.__name__
    )
    
    # Add EXPOSES and PUBLISHES relationships to other_relations
    other_relations["EXPOSES"].update(exposes_rels)
    other_relations["PUBLISHES"].update(publishes_rels)
    
    # Create property entities for ROOT_MODULE
    prop_entities, prop_relations = _create_property_entities_and_relations(
        root_entity,
        source,
        docstring,
        None,  # No signature for modules
        None,  # No resolved signature for modules
        [],  # No decorators for modules
        import_details,
        version
    )
    entities.extend(prop_entities)
    relations.extend(prop_relations)

    # Get all sub-modules using `find_submodules_importlib_resources` and process them
    submodules: set = find_submodules_importlib_resources(module_object.__name__)
    for submodule_path in submodules:
        try:
            submodule_name = submodule_path.split(".")[-1]
            sub_entities, sub_relations = process_member(
                submodule_name,
                importlib.import_module(submodule_path),
                module_object.__name__,
                root_entity,
                processed_paths,
                other_relations,
                version=version,
                parent_obj=module_object,
            )
            entities.extend(sub_entities)
            relations.extend(sub_relations)
        except ModuleNotFoundError as e:
            missing = getattr(e, 'name', '') or ''
            if missing and not missing.startswith(module_object.__name__):
                # External optional dependency; silently skip
                continue
            logging.error(f"Error processing submodule {submodule_path}: {e}")
            logging.error(traceback.format_exc())
            continue
        except Exception as e:
            logging.error(f"Error processing submodule {submodule_path}: {e}")
            logging.error(traceback.format_exc())
            continue

    # Process sub-classes
    for name, member in inspect.getmembers(module_object, inspect.isclass):
        sub_entities, sub_relations = process_member(
            name, member, module_object.__name__, root_entity, processed_paths, other_relations, version=version, parent_obj=module_object
        )
        entities.extend(sub_entities)
        relations.extend(sub_relations)

    # Process functions
    for name, member in inspect.getmembers(module_object, inspect.isfunction):
        sub_entities, sub_relations = process_member(
            name, member, module_object.__name__, root_entity, processed_paths, other_relations, version=version, parent_obj=module_object
        )
        entities.extend(sub_entities)
        relations.extend(sub_relations)

    # Process methods
    for name, member in inspect.getmembers(module_object, inspect.ismethod):
        sub_entities, sub_relations = process_member(
            name, member, module_object.__name__, root_entity, processed_paths, other_relations, version=version, parent_obj=module_object
        )
        entities.extend(sub_entities)
        relations.extend(sub_relations)

    # Build mapping from content_hash to entity for lookups
    hash_to_entity: Dict[str, Entity] = {}
    for entity in entities:
        hash_to_entity[entity.content_hash] = entity

    logging.warning(f"Total EXPOSES relations: {len(other_relations['EXPOSES'])}")
    logging.warning(f"Total PUBLISHES relations: {len(other_relations['PUBLISHES'])}")

    # Clean up temporary import properties from root_entity
    if "import_statements" in root_entity.properties:
        del root_entity.properties["import_statements"]
    if "import_as_aliases" in root_entity.properties:
        del root_entity.properties["import_as_aliases"]

    # Clean up Alias Imports
    for entity in entities:
        if entity.label not in ("ROOT_MODULE", "MODULE"):
            continue

        cleaned_import_aliases: List[Tuple[str, str]] = []
        for key, value in entity.properties.get("import_as_aliases", []):
            # Check if this alias is in EXPOSES or PUBLISHES using content_hash
            found = False
            for from_hash, to_ref in other_relations["EXPOSES"]:
                if from_hash == entity.content_hash and to_ref.name == key:
                    found = True
                    break
            if not found:
                for from_hash, to_ref in other_relations["PUBLISHES"]:
                    if from_hash == entity.content_hash and to_ref.name == key:
                        found = True
                        break
            if found:
                cleaned_import_aliases.append((key, value))
        if cleaned_import_aliases:
            entity.properties["import_as_aliases"] = cleaned_import_aliases

    # Process external parent classes recursively if enabled
    if include_external_parents:
        external_entities, external_relations = _process_external_parent_classes(
            other_relations["INHERITS"],
            _processed_external_classes,
            module_object.__name__,
            other_relations  # Pass other_relations to accumulate INHERITS from external classes
        )
        entities.extend(external_entities)
        relations.extend(external_relations)

    # Convert sets to lists for final output
    other_relations["EXPOSES"] = list(other_relations["EXPOSES"])
    other_relations["PUBLISHES"] = list(other_relations["PUBLISHES"])
    other_relations["INHERITS"] = list(other_relations["INHERITS"])

    logging.info(f"Processed {len(entities)} entities and {len(relations)} relations in {module_object.__name__}.")

    return entities, relations, other_relations
