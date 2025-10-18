import subprocess
import tempfile
import sys
from pathlib import Path
from typing import Dict, Any
import importlib
import json

from lib_sage.libex import (
    get_typed_signature,
    get_function_method_labels,
    get_overloads,
    get_namespaces,
)


class SetEncoder(json.JSONEncoder):
    """Custom JSON encoder that converts sets to a special format."""
    def default(self, obj):
        if isinstance(obj, set):
            try:
                return {"__set__": sorted(list(obj))}
            except TypeError:
                # If items aren't sortable, sort by string representation
                return {"__set__": sorted(list(obj), key=str)}
        return super().default(obj)


def set_decoder(dct):
    """Custom JSON decoder that restores sets from our special format."""
    if "__set__" in dct:
        return set(dct["__set__"])
    return dct


def generate_outputs(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generate outputs for specified library entities.
    
    Args:
        config: Dictionary containing:
            - library: str - Name of the library to install
            - version: str - Version of the library (optional, defaults to latest)
            - entities: List[Dict] - List of entities to process, each containing:
                - path: str - Fully qualified path to the entity (e.g., 'pydantic.BaseModel.__init__')
                - type: str - Type of entity ('function', 'method', 'class')
    
    Returns:
        Dictionary with structure:
            {
                'library': str,
                'version': str,
                'outputs': {
                    'entity_path': {
                        'typed_signature': str,
                        'labels': List[str],
                        'decorators': List[str],
                        'overloads': List[Dict],
                        'namespaces': Dict[str, Any],
                        'runtime_namespaces': Dict[str, str]
                    }
                }
            }
    """
    library = config.get("library")
    version = config.get("version", "")
    entities = config.get("entities", [])
    
    if not library:
        raise ValueError("Library name is required in config")
    
    if not entities:
        raise ValueError("At least one entity is required in config")
    
    # Create temporary virtual environment
    with tempfile.TemporaryDirectory() as temp_dir:
        venv_path = Path(temp_dir) / "venv"
        
        # Create virtual environment
        subprocess.run(
            [sys.executable, "-m", "venv", str(venv_path)],
            check=True,
            capture_output=True
        )
        
        # Determine pip and python paths
        if sys.platform == "win32":
            pip_path = venv_path / "Scripts" / "pip.exe"
            python_path = venv_path / "Scripts" / "python.exe"
        else:
            pip_path = venv_path / "bin" / "pip"
            python_path = venv_path / "bin" / "python"
        
        # Install the library without cache and other stuff
        package_spec = f"{library}=={version}" if version else library
        subprocess.run(
            [str(pip_path), "install", "--no-cache-dir", "--disable-pip-version-check", package_spec],
            check=True,
            capture_output=True
        )
        
        # Now process entities in the temp environment
        outputs = {}
        
        for entity_config in entities:
            entity_path = entity_config.get("path")
            entity_type = entity_config.get("type")
            
            if not all([entity_path, entity_type]):
                continue
            
            try:
                # Parse the fully qualified path
                # e.g., 'pydantic.BaseModel.__init__' -> module='pydantic', parts=['BaseModel', '__init__']
                path_parts = entity_path.split(".")
                
                # Find the module by trying progressively longer prefixes
                module = None
                entity_parts = []
                
                for i in range(len(path_parts), 0, -1):
                    try:
                        module_name = ".".join(path_parts[:i])
                        module = importlib.import_module(module_name)
                        entity_parts = path_parts[i:]
                        break
                    except (ImportError, ModuleNotFoundError):
                        continue
                
                if module is None:
                    raise ImportError(f"Could not import module for path: {entity_path}")
                
                # Navigate to the entity
                entity_obj = module
                parent_obj = None
                
                for part in entity_parts:
                    parent_obj = entity_obj
                    entity_obj = getattr(entity_obj, part)
                
                # For methods, parent_obj will be the class
                if entity_type == "method" and not hasattr(parent_obj, "__module__"):
                    parent_obj = None
                
                # Generate outputs for this entity
                entity_outputs = {}
                
                # Get typed signature
                try:
                    entity_outputs["typed_signature"] = get_typed_signature(
                        entity_obj, 
                        include_overloads=True
                    )
                except Exception as e:
                    entity_outputs["typed_signature"] = f"Error: {str(e)}"
                
                # Get function/method labels and decorators
                try:
                    entity_name = entity_path.split(".")[-1]
                    labels, decorators = get_function_method_labels(
                        entity_obj,
                        entity_name,
                        parent_obj=parent_obj
                    )
                    entity_outputs["labels"] = labels
                    entity_outputs["decorators"] = decorators
                except Exception as e:
                    entity_outputs["labels"] = []
                    entity_outputs["decorators"] = []
                    entity_outputs["labels_error"] = str(e)
                
                # Get overloads
                try:
                    entity_name = entity_path.split(".")[-1]
                    overloads = get_overloads(entity_obj)
                    if overloads:
                        entity_outputs["overloads"] = [
                            {
                                "signature": str(get_typed_signature(ov, include_overloads=False)),
                                "name": getattr(ov, "__name__", entity_name)
                            }
                            for ov in overloads
                        ]
                    else:
                        entity_outputs["overloads"] = []
                except Exception as e:
                    entity_outputs["overloads"] = []
                    entity_outputs["overloads_error"] = str(e)
                
                # Get namespaces (for modules or classes with source)
                try:
                    import inspect
                    import re
                    source = inspect.getsource(entity_obj)
                    namespaces, runtime_ns = get_namespaces(source, module)
                    
                    # Helper function to normalize file paths in strings
                    def normalize_path(val_str: str, key_name: str) -> str:
                        """Remove absolute paths from __file__, __cached__, and similar keys."""
                        # For __file__ and __cached__, replace absolute path with <PATH_NORMALIZED>
                        if key_name in ("__file__", "__cached__"):
                            # Just indicate it's a path without storing the actual path
                            if val_str.endswith(".py"):
                                return "<PATH:*.py>"
                            elif val_str.endswith(".pyc"):
                                return "<PATH:*.pyc>"
                            elif val_str.endswith((".so", ".pyd", ".dll")):
                                return "<PATH:*.(extension)>"
                            else:
                                return "<PATH:*>"
                        
                        # For other values that contain file paths
                        # Match common path patterns: /path/to/file or C:\path\to\file
                        if "/" in val_str or "\\" in val_str:
                            # Check if it looks like an absolute path
                            if (val_str.startswith("/") or 
                                (len(val_str) > 2 and val_str[1] == ":" and val_str[2] in ("/", "\\"))):
                                # Extract just the filename if it's a file path
                                parts = val_str.replace("\\", "/").split("/")
                                filename = parts[-1] if parts else val_str
                                return f"<PATH:.../{filename}>"
                        
                        return val_str
                    
                    # Convert namespaces to serializable format
                    serializable_ns = {}
                    for key, value in namespaces.items():
                        try:
                            # Keep sets as-is (will be handled by SetEncoder)
                            if isinstance(value, set):
                                serializable_ns[key] = value
                            # Store type/class names as strings
                            elif hasattr(value, "__name__"):
                                serializable_ns[key] = f"{value.__module__}.{value.__name__}"
                            else:
                                value_str = str(value)
                                
                                # Replace memory addresses with placeholder for deterministic comparison
                                if " object at 0x" in value_str:
                                    # Extract object type and create placeholder
                                    # e.g., "<_frozen_importlib_external.SourceFileLoader object at 0x...>" 
                                    # becomes "<NON_DETERMINISTIC:_frozen_importlib_external.SourceFileLoader>"
                                    obj_type = value_str.split(" object at ")[0].lstrip("<")
                                    serializable_ns[key] = f"<NON_DETERMINISTIC:{obj_type}>"
                                elif value_str.startswith("ModuleSpec(") and " object at 0x" in value_str:
                                    # Extract module name from ModuleSpec and create placeholder
                                    # e.g., "ModuleSpec(name='pydantic.fields', ...)" 
                                    # becomes "<NON_DETERMINISTIC:ModuleSpec(name='pydantic.fields')>"
                                    match = re.search(r"name='([^']+)'", value_str)
                                    if match:
                                        module_name = match.group(1)
                                        serializable_ns[key] = f"<NON_DETERMINISTIC:ModuleSpec(name='{module_name}')>"
                                    else:
                                        serializable_ns[key] = "<NON_DETERMINISTIC:ModuleSpec>"
                                # Replace module file paths with just module name for deterministic comparison
                                elif value_str.startswith("<module '") and "' from '" in value_str:
                                    # Extract module name: "<module 'typing_inspection.typing_objects' from '/path/to/file.py'>"
                                    # becomes "<module 'typing_inspection.typing_objects'>"
                                    match = re.match(r"<module '([^']+)' from '.*'>", value_str)
                                    if match:
                                        module_name = match.group(1)
                                        serializable_ns[key] = f"<module '{module_name}'>"
                                    else:
                                        serializable_ns[key] = value_str
                                else:
                                    # Apply path normalization for keys like __file__, __cached__
                                    serializable_ns[key] = normalize_path(value_str, key)
                        except:
                            try:
                                value_str = str(value)
                                # Replace memory addresses with placeholder
                                if " object at 0x" in value_str:
                                    obj_type = value_str.split(" object at ")[0].lstrip("<")
                                    serializable_ns[key] = f"<NON_DETERMINISTIC:{obj_type}>"
                                # Replace module paths
                                elif value_str.startswith("<module '") and "' from '" in value_str:
                                    match = re.match(r"<module '([^']+)' from '.*'>", value_str)
                                    if match:
                                        module_name = match.group(1)
                                        serializable_ns[key] = f"<module '{module_name}'>"
                                    else:
                                        serializable_ns[key] = value_str
                                else:
                                    # Apply path normalization
                                    serializable_ns[key] = normalize_path(value_str, key)
                            except:
                                pass
                    
                    entity_outputs["namespaces"] = serializable_ns
                    entity_outputs["runtime_namespaces"] = runtime_ns
                except Exception as e:
                    entity_outputs["namespaces"] = {}
                    entity_outputs["runtime_namespaces"] = {}
                    entity_outputs["namespaces_error"] = str(e)
                
                # Store outputs using the entity path as key
                outputs[entity_path] = entity_outputs
                
            except Exception as e:
                outputs[entity_path] = {
                    "error": str(e)
                }
    
    return {
        "library": library,
        "version": version or "latest",
        "outputs": outputs
    }
