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
from typing_extensions import Dict, List, Optional, Tuple

from .utils.metadata_utils import (
    get_distribution_top_level_modules,
    get_package_version,
    get_package_metadata,
    PackageNotFoundError
)

from .models import Entity, Relationship
from .module_processor import process_module, _parse_name_and_version


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
    # First, try importing the package name directly - this handles cases like pytest
    top_level_modules = []
    try:
        test_import = importlib.import_module(package_name)
        # If successful and it's a real package (not just a namespace), use it
        if hasattr(test_import, '__file__') or hasattr(test_import, '__path__'):
            logging.info(f"Package {package_name} is directly importable, adding it as top-level module")
            top_level_modules.append(package_name)
    except (ImportError, ModuleNotFoundError):
        logging.debug(f"Package name {package_name} is not directly importable, will check distribution metadata")
    
    # Check distribution metadata for all matching packages
    # Use metadata utils to find top-level modules (supports Python < 3.10 via fallback)
    dist_modules = get_distribution_top_level_modules(package_name)
    
    for mod in dist_modules:
        if mod not in top_level_modules:
            top_level_modules.append(mod)

    if not top_level_modules:
        logging.warning(f"No top-level modules found for package {package_name}")
        return []
    
    logging.info(f"Found {len(top_level_modules)} top-level module(s) for package {package_name}: {top_level_modules}")
    return top_level_modules


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
    install_method: str = "pip"
) -> Tuple[List[Entity], List[Relationship], Dict]:
    """
    **PRIMARY API** - Process all top-level modules associated with a package name.
    
    This function finds all packages/distributions that contain the given package_name,
    processes each of their top-level modules, and combines the results.
    Each top-level module is treated as a ROOT_MODULE.

    Args:
        package_name (str): The name of the package.
        version (Optional[str]): Version of the package.
        install_method (str): Method to use for installation: 'pip', 'uv', or 'conda'. Default is 'pip'.
        
    Returns:
        Tuple[List[Entity], List[Relationship], Dict]: Combined entities, relations, and other relations
            from all top-level modules associated with the package.
    """
    pkg_name, parsed_version = _parse_name_and_version(package_name, version)
    version = parsed_version
    top_level_modules = get_top_level_modules_for_package(pkg_name)

    if not top_level_modules:
        logging.info(f"Package '{pkg_name}' not found. Attempting to install using {install_method}...")
        try:
            # Install specific version if provided, otherwise latest
            install_spec = f"{pkg_name}=={version}" if version else pkg_name
            
            # Determine install command based on method
            if install_method == "uv":
                install_cmd = ["uv", "pip", "install", install_spec]
            elif install_method == "conda":
                # For conda, use conda install with -c conda-forge or just the package name
                if version:
                    install_cmd = ["conda", "install", "-y", f"{pkg_name}={version}"]
                else:
                    install_cmd = ["conda", "install", "-y", pkg_name]
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
            return [], [], {
                "INHERITS": [], "EXPOSES": [], "PUBLISHES": [],
                "EXPOSES_ALL": [], "PUBLISHES_ALL": []
            }
    
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
                    reinstall_cmd = ["uv", "pip", "install", install_spec]
                elif install_method == "conda":
                    reinstall_cmd = ["conda", "install", "-y", "--force-reinstall", f"{pkg_name}={version}"]
                else:  # pip
                    reinstall_cmd = [sys.executable, "-m", "pip", "install", "--force-reinstall", install_spec]
                
                subprocess.run(reinstall_cmd, check=True, capture_output=True)
                # Verify again after reinstall
                installed_version = get_package_version(pkg_name)
                if installed_version != version:
                    logging.error(f"Failed to install version {version}. Current version: {installed_version}")
                    return [], [], {"INHERITS": [], "EXPOSES": [], "PUBLISHES": []}
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
            return [], [], {
                "INHERITS": [], "EXPOSES": [], "PUBLISHES": [],
                "EXPOSES_ALL": [], "PUBLISHES_ALL": []
            }
        except PackageNotFoundError:
            logging.error(f"Package '{pkg_name}' metadata not found")
            return [], [], {
                "INTERNAL_INHERITS": [], "EXTERNAL_INHERITS": [], "EXPOSES": [], "PUBLISHES": [],
                "EXPOSES_ALL": [], "PUBLISHES_ALL": []
            }
    
    # Get top-level modules after version verification
    top_level_modules = get_top_level_modules_for_package(pkg_name)
    if not top_level_modules:
        logging.error(f"Package '{pkg_name}' not found after installation.")
        return [], [], {
            "INTERNAL_INHERITS": [], "EXTERNAL_INHERITS": [], "EXPOSES": [], "PUBLISHES": [],
            "EXPOSES_ALL": [], "PUBLISHES_ALL": []
        }
    
    # Process all top-level modules and combine results
    all_entities: List[Entity] = []
    all_relations: List[Relationship] = []
    combined_other_relations: Dict[str, List] = {
        "INTERNAL_INHERITS": [], 
        "EXTERNAL_INHERITS": [], 
        "EXPOSES": [], 
        "PUBLISHES": [],
        "EXPOSES_ALL": [],
        "PUBLISHES_ALL": []
    }
    
    # Create DISTRIBUTION_PACKAGE entity with metadata
    dist_entity = None
    try:
        # We use the installed version if available, otherwise the requested version or None
        current_version = get_package_version(pkg_name)
        
        # Use reconciled metadata (combines local and PyPI data)
        metadata = get_package_metadata(pkg_name, current_version)
        
        dist_props = {
            "version": current_version,
            "python_requires": metadata.get("python_requires"),
            "supported_python_versions": metadata.get("supported_python_versions"),
            "dependencies": metadata.get("dependencies"),
            "extras": metadata.get("extras"),
            "pypi_metadata_found": metadata.get("pypi_metadata_found")
        }
        
        dist_entity = Entity(
            name=pkg_name,
            labels=["DISTRIBUTION_PACKAGE"],
            properties=dist_props
        )
        all_entities.append(dist_entity)
        logging.info(f"Created DISTRIBUTION_PACKAGE entity for '{pkg_name}' version {current_version}")
        
    except PackageNotFoundError:
        logging.warning(f"Could not create DISTRIBUTION_PACKAGE for {pkg_name}: metadata not found")

    logging.info(f"Processing package '{pkg_name}' with {len(top_level_modules)} top-level module(s): {top_level_modules}")
    
    for top_level_module in top_level_modules:
        logging.info(f"Processing top-level module '{top_level_module}' for package '{pkg_name}'...")
        try:
            entities, relations, other_relations = process_module(top_level_module, version=version)
            
            # Link DISTRIBUTION_PACKAGE to IMPORT_PACKAGE (root of the module)
            if dist_entity and entities:
                # The first entity returned by process_module is the root module (IMPORT_PACKAGE)
                import_pkg_entity = entities[0]
                # Verify it's an IMPORT_PACKAGE just to be safe
                if "IMPORT_PACKAGE" in import_pkg_entity.labels:
                    rel = Relationship(
                        from_entity=dist_entity,
                        to_entity=import_pkg_entity,
                        label="PROVIDES",
                        properties={}
                    )
                    all_relations.append(rel)
            
            all_entities.extend(entities)
            all_relations.extend(relations)
            
            # Combine other_relations
            for rel_type in ["INTERNAL_INHERITS", "EXTERNAL_INHERITS", "EXPOSES", "PUBLISHES", "EXPOSES_ALL", "PUBLISHES_ALL"]:
                if rel_type in other_relations:
                    combined_other_relations[rel_type].extend(other_relations[rel_type])

        except Exception as e:
            logging.error(f"Error processing top-level module '{top_level_module}' for package '{pkg_name}': {e}")
            logging.error(traceback.format_exc())
            continue
    
    # Deduplicate other_relations
    for rel_type in ["INTERNAL_INHERITS", "EXTERNAL_INHERITS", "EXPOSES", "PUBLISHES", "EXPOSES_ALL", "PUBLISHES_ALL"]:
        combined_other_relations[rel_type] = list(set(combined_other_relations[rel_type]))
    
    logging.info(f"Completed processing package '{pkg_name}': "
                f"{len(all_entities)} total entities, {len(all_relations)} total relations")
    
    return all_entities, all_relations, combined_other_relations
