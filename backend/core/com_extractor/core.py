"""
Core API - Primary package processing entry point.

This module provides process_package as the main API for extracting
entities and relationships from Python packages.
"""

import importlib
import logging
import subprocess
import sys
import traceback
import os
from typing_extensions import Any, Dict, List, Optional

from .utils.metadata_utils import (
    get_distribution_top_level_modules,
    get_package_version,
    get_package_metadata,
    PackageNotFoundError
)

from .models import Entity, Relationship, ExtractionResult
from .dynamic_analysis.processor import process_module, _parse_name_and_version
from .utils.alias_finder import find_aliases
from .static_analysis.alias_finder import find_aliases_static
from .static_analysis.traversal import process_package_static

def _locate_package_path(package_name: str, search_paths: Optional[List[str]] = None) -> Optional[str]:
    path_parts = package_name.split(".")
    candidates = search_paths if search_paths is not None else list(sys.path)
    for root in candidates:
        if not root:
            continue
        base_path = os.path.join(root, *path_parts)
        package_init = os.path.join(base_path, "__init__.py")
        if os.path.isfile(package_init):
            return base_path
        if os.path.isdir(base_path):
            return base_path
        module_file = f"{base_path}.py"
        if os.path.isfile(module_file):
            return module_file
    return None


def get_top_level_modules_for_package(package_name: str) -> List[str]:
    """
    Get all top-level modules associated with a package name.
    
    This function finds all packages/distributions that contain the given package_name
    and returns all their top-level modules.

    Args:
        package_name (str): The name of the package.

    Returns:
        List[str]: List of top-level modules for all matching packages.
    """
    top_level_modules = []

    dist_modules = get_distribution_top_level_modules(package_name)

    for mod in dist_modules:
        if mod not in top_level_modules:
            top_level_modules.append(mod)

    if package_name not in top_level_modules:
        top_level_modules.append(package_name)

    if not top_level_modules:
        logging.warning(f"No top-level modules found for package {package_name}")
        return []
    
    logging.info(f"Found {len(top_level_modules)} top-level module(s) for package {package_name}: {top_level_modules}")
    return top_level_modules


def process_package_from_module_paths(
    package_name: str,
    version: Optional[str],
    module_paths: Dict[str, str],
) -> ExtractionResult:
    pkg_name, parsed_version = _parse_name_and_version(package_name, version)
    version = parsed_version

    all_entities: List[Entity] = []
    all_relations: List[Relationship] = []
    combined_other_relations: Dict[str, Any] = {
        "INTERNAL_INHERITS": [],
        "EXTERNAL_INHERITS": [],
        "EXPOSES": [],
        "PUBLISHES": [],
        "EXPOSES_ALL": [],
        "PUBLISHES_ALL": [],
    }

    dist_entity = None
    current_version = version
    metadata = {}

    try:
        current_version = get_package_version(pkg_name)
    except Exception:
        current_version = version

    try:
        metadata = get_package_metadata(pkg_name, current_version)
    except Exception:
        metadata = {}

    dist_props = {
        "version": current_version,
        "python_requires": metadata.get("python_requires"),
        "supported_python_versions": metadata.get("supported_python_versions"),
        "dependencies": metadata.get("dependencies"),
        "extras": metadata.get("extras"),
        "pypi_metadata_found": metadata.get("pypi_metadata_found", False),
    }

    dist_entity = Entity(
        name=pkg_name,
        labels=["DISTRIBUTION_PACKAGE"],
        properties=dist_props,
    )
    dist_entity.type = "DISTRIBUTION_PACKAGE"
    all_entities.append(dist_entity)

    logging.info(
        f"Processing package '{pkg_name}' with {len(module_paths)} top-level module(s): {list(module_paths.keys())}"
    )

    for top_level_module, pkg_path in module_paths.items():
        logging.info(f"Processing top-level module '{top_level_module}' for package '{pkg_name}'...")
        try:
            if not pkg_path or not os.path.exists(pkg_path):
                logging.warning(f"Path not found for module '{top_level_module}': {pkg_path}")
                continue

            logging.info(f"Processing static analysis for {top_level_module} at {pkg_path}")
            s_entities, s_relations, s_other_relations = process_package_static(
                pkg_path,
                top_level_module,
                version=version,
            )

            entities = s_entities
            relations = s_relations
            other_relations = s_other_relations

            if dist_entity and entities:
                import_pkg_entity = next((e for e in entities if e.name == top_level_module), None)

                if not import_pkg_entity:
                    import_pkg_entity = next((e for e in entities if "MODULE" in e.labels), None)

                if import_pkg_entity:
                    if "IMPORT_PACKAGE" not in import_pkg_entity.labels:
                        import_pkg_entity.labels.append("IMPORT_PACKAGE")

                    rel = Relationship(
                        from_entity=dist_entity,
                        to_entity=import_pkg_entity,
                        label="PROVIDES",
                        properties={},
                    )
                    all_relations.append(rel)

            all_entities.extend(entities)
            all_relations.extend(relations)

            if other_relations:
                for rel_type in [
                    "INTERNAL_INHERITS",
                    "EXTERNAL_INHERITS",
                    "EXPOSES",
                    "PUBLISHES",
                    "EXPOSES_ALL",
                    "PUBLISHES_ALL",
                ]:
                    if rel_type in other_relations:
                        combined_other_relations[rel_type].extend(other_relations[rel_type])

        except Exception as e:
            logging.error(f"Error processing top-level module '{top_level_module}' for package '{pkg_name}': {e}")
            logging.error(traceback.format_exc())
            continue

    for rel_type in [
        "INTERNAL_INHERITS",
        "EXTERNAL_INHERITS",
        "EXPOSES",
        "PUBLISHES",
        "EXPOSES_ALL",
        "PUBLISHES_ALL",
    ]:
        combined_other_relations[rel_type] = list(set(combined_other_relations[rel_type]))

    try:
        logging.info("Finding aliases for extracted entities...")
        try:
            aliases = find_aliases_static(all_entities, all_relations, combined_other_relations)
        except Exception:
            aliases = find_aliases(all_entities, all_relations, combined_other_relations)
        logging.info(f"Found aliases for {len(aliases)} entities")
    except Exception as e:
        logging.error(f"Error finding aliases: {e}")
        logging.error(traceback.format_exc())
        aliases = {}

    logging.info(
        f"Completed processing package '{pkg_name}': "
        f"{len(all_entities)} total entities, {len(all_relations)} total relations"
    )

    return ExtractionResult(
        entities=all_entities,
        relations=all_relations,
        other_relations=combined_other_relations,
        aliases=aliases,
    )


def get_top_level_module(package_name: str) -> str:
    """
    Get the top-level module of a package, preferring the package name itself if importable.
    
    Some packages (like pytest) have different internal module names (_pytest) but expose
    a public API through the package name. This function tries the package name first,
    then falls back to the distribution's top-level modules.

    Args:
        package_name (str): The name of the package.

    Returns:
        str: The top-level module of the package.
    """
    modules = get_top_level_modules_for_package(package_name)
    if not modules:
        return ""
    
    # Prefer the module that matches the package name
    if len(modules) > 1:
        for mod in modules:
            if mod == package_name or mod.replace('_', '-') == package_name.replace('_', '-'):
                logging.info(f"Found matching top-level module {mod} for package {package_name}")
                return mod
        logging.info(f"Multiple top-level modules found for {package_name}: {modules}, using first: {modules[0]}")
    
    return modules[0]


def process_package(
    package_name: str,
    version: Optional[str] = None,
    install_method: str = "pip",
    python: Optional[str] = None
) -> ExtractionResult:
    """
    **PRIMARY API** - Process all top-level modules associated with a package name.
    
    This function finds all packages/distributions that contain the given package_name,
    processes each of their top-level modules, and combines the results.
    Each top-level module is treated as a IMPORT_PACKAGE.

    Args:
        package_name (str): The name of the package.
        version (Optional[str]): Version of the package.
        install_method (str): Method to use for installation: 'pip' or 'uv'. Default is 'pip'.
        python (Optional[str]): Python version or path to use with uv.
        
    Returns:
        ExtractionResult: Combined entities, relations, and other relations
            from all top-level modules associated with the package.
    """
    pkg_name, parsed_version = _parse_name_and_version(package_name, version)
    version = parsed_version
    top_level_modules = get_top_level_modules_for_package(pkg_name)

    if python is not None:
        logging.info(f"Using Python interpreter '{python}' for installation with uv")

    if not top_level_modules:
        logging.info(f"Package '{pkg_name}' not found. Attempting to install using {install_method}...")
        try:
            # Install specific version if provided, otherwise latest
            install_spec = f"{pkg_name}=={version}" if version else pkg_name
            
            # Determine install command based on method
            if install_method == "uv":
                install_cmd = ["uv", "pip", "install"]
                # Explicitly use the provided python or current interpreter to avoid system fallback
                uv_python = python or sys.executable
                install_cmd.extend(["--python", uv_python])
                install_cmd.append(install_spec)
            else:  # pip (default)
                install_cmd = [sys.executable, "-m", "pip", "install", install_spec]
            
            subprocess.run(install_cmd, check=True)
            logging.info(f"Package '{install_spec}' installed successfully using {install_method}.")
        except subprocess.CalledProcessError as e:
            error_output = getattr(e, 'stderr', None) or str(e)
            logging.error(f"Failed to install package '{pkg_name}' using {install_method}: {e}")
            
            # Check for common Python version incompatibility messages
            if any(msg in error_output for msg in [
                "requires Python", "python_requires", "No matching distribution",
                "Could not find a version", "incompatible", "not supported"
            ]):
                py_version = f"{sys.version_info.major}.{sys.version_info.minor}"
                logging.error(f"Package '{install_spec}' may not be compatible with Python {py_version}")
                logging.error(f"Installation error details: {error_output}")
            return ExtractionResult(entities=[], relations=[], other_relations={
                "INTERNAL_INHERITS": [], "EXTERNAL_INHERITS": [], "EXPOSES": [], "PUBLISHES": [],
                "EXPOSES_ALL": [], "PUBLISHES_ALL": []
            })
    
    # Verify installed version matches requested version
    if version:
        try:
            installed_version = get_package_version(pkg_name)
            if version in installed_version:
                logging.info(f"Package {pkg_name}=={version} is installed")
            else:
                logging.warning(f"Version mismatch: requested {version}, found {installed_version}")
                logging.info(f"Attempting to install correct version using {install_method}...")
                install_spec = f"{pkg_name}=={version}"
                
                # Determine reinstall command based on method
                if install_method == "uv":
                    reinstall_cmd = ["uv", "pip", "install"]
                    # Explicitly use the provided python or current interpreter to avoid system fallback
                    uv_python = python or sys.executable
                    reinstall_cmd.extend(["--python", uv_python])
                    reinstall_cmd.append(install_spec)
                else:  # pip
                    reinstall_cmd = [sys.executable, "-m", "pip", "install", "--force-reinstall", install_spec]
                
                subprocess.run(reinstall_cmd, check=True, capture_output=True)
                # Verify again after reinstall
                installed_version = get_package_version(pkg_name)
                if installed_version != version:
                    logging.error(f"Failed to install version {version}. Current version: {installed_version}")
                    return ExtractionResult(entities=[], relations=[], other_relations={
                        "INTERNAL_INHERITS": [], "EXTERNAL_INHERITS": [], "EXPOSES": [], "PUBLISHES": [],
                        "EXPOSES_ALL": [], "PUBLISHES_ALL": []
                    })
                logging.info(f"Successfully installed {pkg_name}=={version}")
        except subprocess.CalledProcessError as e:
            error_output = getattr(e, 'stderr', None) or str(e)
            logging.error(f"Failed to reinstall package '{pkg_name}=={version}': {e}")
            
            # Check for Python version incompatibility
            if any(msg in str(error_output) for msg in [
                "requires Python", "python_requires", "No matching distribution",
                "Could not find a version", "incompatible", "not supported"
            ]):
                py_version = f"{sys.version_info.major}.{sys.version_info.minor}"
                logging.error(f"Package '{pkg_name}=={version}' may not be compatible with Python {py_version}")
                logging.error(f"Try using a different Python version or a different package version")
            return ExtractionResult(entities=[], relations=[], other_relations={
                "INTERNAL_INHERITS": [], "EXTERNAL_INHERITS": [], "EXPOSES": [], "PUBLISHES": [],
                "EXPOSES_ALL": [], "PUBLISHES_ALL": []
            })
        except PackageNotFoundError:
            logging.error(f"Package '{pkg_name}' metadata not found")
            return ExtractionResult(entities=[], relations=[], other_relations={
                "INTERNAL_INHERITS": [], "EXTERNAL_INHERITS": [], "EXPOSES": [], "PUBLISHES": [],
                "EXPOSES_ALL": [], "PUBLISHES_ALL": []
            })
    
    # Get top-level modules after version verification
    top_level_modules = get_top_level_modules_for_package(pkg_name)
    if not top_level_modules:
        logging.error(f"Package '{pkg_name}' not found after installation.")
        return ExtractionResult(entities=[], relations=[], other_relations={
            "INTERNAL_INHERITS": [], "EXTERNAL_INHERITS": [], "EXPOSES": [], "PUBLISHES": [],
            "EXPOSES_ALL": [], "PUBLISHES_ALL": []
        })
    
    module_paths: Dict[str, str] = {}
    for top_level_module in top_level_modules:
        pkg_path = _locate_package_path(top_level_module)
        if pkg_path and os.path.exists(pkg_path):
            module_paths[top_level_module] = pkg_path
        else:
            logging.warning(f"Could not locate path for top-level module '{top_level_module}'")

    if not module_paths:
        logging.error(f"No module paths found for package '{pkg_name}'")
        return ExtractionResult(entities=[], relations=[], other_relations={
            "INTERNAL_INHERITS": [], "EXTERNAL_INHERITS": [], "EXPOSES": [], "PUBLISHES": [],
            "EXPOSES_ALL": [], "PUBLISHES_ALL": []
        })

    return process_package_from_module_paths(pkg_name, version, module_paths)
