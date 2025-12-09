"""
Source code introspection and AST utilities.

This module provides utilities for extracting source code, docstrings,
import statements, and submodules from Python objects.
"""

import ast
import functools
import importlib
import importlib.resources
import importlib.util
import inspect
import logging
import os
import re
import subprocess
import traceback
import types
from tokenize import TokenError
from typing import Any, Dict, List, Optional, Set, Tuple


def _normalize_signature(signature_str: str) -> str:
    """
    Normalize a signature string by removing memory addresses from object representations.
    
    This fixes issues where function/lambda objects in default parameters include memory
    addresses (e.g., '<function <lambda> at 0x104432980>'), which change between runs
    and cause incorrect duplicate detection.
    
    Args:
        signature_str: Raw signature string from inspect.signature()
    
    Returns:
        Normalized signature with memory addresses removed
    
    Examples:
        '(fin, fout, delim="\\n", callback=<function <lambda> at 0x104432980>)'
        -> '(fin, fout, delim="\\n", callback=<function <lambda>>)'
        
        '(x=<MyClass object at 0x7f8b8c6d4e80>)'
        -> '(x=<MyClass object>)'
    """
    pattern = r' at 0x[0-9a-fA-F]+>'
    normalized = re.sub(pattern, '>', signature_str)
    return normalized


def get_fully_qualified_name(cls):
    """Get the fully qualified name of a class."""
    return f"{cls.__module__}.{cls.__qualname__}"


def get_raw_source(obj) -> Optional[str]:
    """
    Get raw source code directly from the source file, bypassing inspect module.
    
    This provides version-independent source extraction by reading directly from
    the file and using AST line numbers. This is preferable for version comparison
    and diffing as it preserves the original source exactly as written.
    
    Args:
        obj: The Python object to get source for
        
    Returns:
        Raw source code string from file, or None if unavailable
    """
    try:
        # Get the source file
        source_file = inspect.getsourcefile(obj)
        if not source_file:
            return None
        
        # Read the entire file
        with open(source_file, 'r', encoding='utf-8') as f:
            full_source = f.read()
        
        # Parse with AST to find line numbers
        try:
            tree = ast.parse(full_source, filename=source_file)
        except SyntaxError:
            return None
        
        # Find the matching node
        obj_name = getattr(obj, '__name__', None)
        if not obj_name:
            return None
        
        # For methods, we need to match the class context too
        obj_qualname = getattr(obj, '__qualname__', obj_name)
        
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                # For nested definitions (methods), check qualname match
                if node.name == obj_name or obj_qualname.endswith(f".{node.name}"):
                    # Extract source from the node's line numbers
                    lines = full_source.splitlines()
                    if hasattr(node, 'lineno') and hasattr(node, 'end_lineno'):
                        # Get lines from lineno-1 to end_lineno (1-indexed to 0-indexed)
                        source_lines = lines[node.lineno - 1:node.end_lineno]
                        return '\n'.join(source_lines)
        
        return None
    except Exception as e:
        logging.debug(f"Error getting raw source for {obj}: {e}")
        return None


def safe_get_source(obj) -> str:
    """
    Safely get the source code of an object, prioritizing raw source from file.
    
    This function prioritizes raw source (version-independent) over inspect.getsource()
    for better consistency across Python versions. Falls back to inspect and finally
    to a normalized representation if neither works.
    
    Args:
        obj: The Python object to get source for
        
    Returns:
        Source code string, or a normalized representation if source unavailable
    """
    # First try: Get raw source directly from file (version-independent)
    raw_source = get_raw_source(obj)
    if raw_source:
        return raw_source
    
    # Second try: Use inspect.getsource as fallback
    try:
        return inspect.getsource(obj)
    except (OSError, TypeError, TokenError) as e:
        logging.debug(f"Could not get source for {obj}: {e}")
        # Final fallback: normalize repr to remove memory addresses
        return f"# Representation:\n{_normalize_signature(repr(obj))}"


def safe_get_docstring(obj) -> str:
    """
    Safely get the docstring of an object.
    
    Args:
        obj: The Python object to get docstring for
        
    Returns:
        Docstring or empty string if unavailable
    """
    try:
        return inspect.getdoc(obj) or ""
    except (OSError, TypeError):
        # Normalize repr to remove memory addresses
        return f"# Representation:\n{_normalize_signature(repr(obj))}"


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
        imports: List[str] = []

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                # Handles: import os, sys
                import_statement = "import " + ", ".join(
                    alias.name + (f" as {alias.asname}" if alias.asname else "") for alias in node.names
                )
                imports.append(import_statement)
            elif isinstance(node, ast.ImportFrom):
                # Handles: from datetime import date, datetime as dt
                names = ", ".join(
                    alias.name + (f" as {alias.asname}" if alias.asname else "") for alias in node.names
                )
                module = node.module or ""
                level = getattr(node, "level", 0) or 0
                if level > 0:
                    dots = "." * level
                    module = f"{dots}{module}" if module else dots
                import_statement = f"from {module} import {names}"
                imports.append(import_statement)

        return "\n".join(imports)
    except Exception:
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
    def resolve_relative(module: Optional[str], level: int) -> str:
        if not level:
            return module or ""
        parts = current_file_path.split(".")
        if parts:
            parts = parts[:-1]
        up = max(level, 0)
        if up > len(parts):
            base: List[str] = []
        else:
            base = parts[: len(parts) - up + 1]
        if module:
            base.append(module)
        return ".".join([p for p in base if p])

    try:
        tree = ast.parse(source_code)
        aliases: List[Tuple[str, str]] = []

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.asname:
                        aliases.append((alias.name, alias.asname))
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                level = getattr(node, "level", 0) or 0
                full_module = resolve_relative(module, level)
                for alias in node.names:
                    if alias.asname:
                        if full_module:
                            aliases.append((f"{full_module}.{alias.name}", alias.asname))
                        else:
                            base = resolve_relative(None, level)
                            full_name = f"{base}.{alias.name}" if base else alias.name
                            aliases.append((full_name, alias.asname))
        return aliases
    except Exception:
        return []


@functools.lru_cache(maxsize=128)
def get_unused_imports(module_name: str, imported_names: frozenset) -> Dict[str, str]:
    """
    Get the list of unused imports in a module using flake8.
    Also checks if imports are only used in __all__ (re-exports) and treats them as unused.
    
    Results are cached per module_name for optimization.

    Args:
        module_name (str): The name of the module.
        imported_names (frozenset): The set of fully qualified imported names (frozenset for hashability).

    Returns:
        Dict[str, str]: Mapping from FQN to exact import statement.
                       e.g., {'pandas.DataFrame': 'from pandas import DataFrame',
                              'os.path': 'import os.path'}
    """
    # Convert frozenset back to set for internal use
    imported_names_set: Set[str] = set(imported_names)
    
    try:
        # Get the full file path of the module
        module = importlib.import_module(module_name)
        module_file_path = module.__file__
        logging.debug(f"Checking unused imports for {module_name} at {module_file_path}...")

        # Run flake8 and capture output
        # Note: flake8 returns exit code 1 when it finds violations, which is expected behavior
        # So we use check=False to avoid raising an exception
        process = None
        if os.name == 'nt':
            process = subprocess.run(
                ["python", "-m", "flake8", "--select", "F401", module_file_path],
                capture_output=True,
                text=True,
                check=False,
                shell=True,
            )
        else:
            # For Unix-like systems, use shell=False
            process = subprocess.run(
                ["python", "-m", "flake8", "--select", "F401", module_file_path],
                capture_output=True,
                text=True,
                check=False,
                shell=False,
            )

        # Check if flake8 command failed to run (not just found violations)
        # Exit code 1 means violations found (expected), > 1 means command failed
        if process.returncode > 1:
            logging.warning(f"flake8 command failed for {module_name} with exit code {process.returncode}")
            if process.stderr:
                logging.debug(f"flake8 stderr: {process.stderr}")
            return {}

        output = process.stdout
        unused_simple_names: Set[str] = set()  # Simple names from flake8

        # Parse the output for unused import errors (F401), extracting the simple names
        for line in output.splitlines():
            match = re.search(r":\d+:(\d+): F401 '(.*)' imported but unused", line)
            if match:
                unused_simple_names.add(match.group(2))
        
        # Check for imports that are only used in __all__ (re-exports without actual usage)
        # Parse the module source to find imports and __all__
        try:
            source = inspect.getsource(module)
            tree = ast.parse(source)
            
            # Extract __all__ if it exists
            all_names: Set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name) and target.id == "__all__":
                            # Extract names from __all__ list
                            if isinstance(node.value, (ast.List, ast.Tuple)):
                                for elt in node.value.elts:
                                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                        all_names.add(elt.value)
                                    elif hasattr(ast, 'Str') and isinstance(elt, ast.Str):  # py<3.8
                                        all_names.add(elt.s)  # type: ignore
            
            if all_names:
                logging.debug(f"Found __all__ in {module_name} with {len(all_names)} names")
                
                # For each imported name, check if it's ONLY in __all__ and nowhere else
                # Build a map of simple names to full paths
                simple_name_to_full: Dict[str, str] = {}
                for full_name in imported_names:
                    simple = full_name.split(".")[-1]
                    simple_name_to_full[simple] = full_name
                
                # Check each name in __all__
                for all_name in all_names:
                    if all_name in simple_name_to_full:
                        full_path = simple_name_to_full[all_name]
                        
                        # Count usages outside of __all__ and import statements
                        usage_count = 0
                        for node in ast.walk(tree):
                            # Skip __all__ assignments
                            if isinstance(node, ast.Assign):
                                for target in node.targets:
                                    if isinstance(target, ast.Name) and target.id == "__all__":
                                        continue
                            
                            # Skip import statements
                            if isinstance(node, (ast.Import, ast.ImportFrom)):
                                continue
                            
                            # Count actual usage
                            if isinstance(node, ast.Name) and node.id == all_name:
                                # Check if this is not in __all__ assignment context
                                usage_count += 1
                        
                        # If usage_count is 1 or less (just the reference in __all__), it's only exported
                        if usage_count <= 1:
                            unused_simple_names.add(all_name)
                            logging.debug(f"Import '{all_name}' only used in __all__, treating as exposed")
        
        except Exception as e:
            logging.debug(f"Could not parse __all__ for {module_name}: {e}")

        # Now parse the source to extract exact import statements for unused names
        unused_imports: Dict[str, str] = {}  # FQN -> import statement
        
        try:
            source = inspect.getsource(module)
            tree = ast.parse(source)
            
            # Build mapping of simple names to their import statements and FQNs
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    # Handle: import os, sys
                    for alias in node.names:
                        simple_name = alias.asname if alias.asname else alias.name.split('.')[-1]
                        if simple_name in unused_simple_names:
                            fqn = alias.name
                            import_stmt = f"import {alias.name}"
                            if alias.asname:
                                import_stmt += f" as {alias.asname}"
                            unused_imports[fqn] = import_stmt
                
                elif isinstance(node, ast.ImportFrom):
                    # Handle: from module import name [as alias]
                    module = node.module or ""
                    for alias in node.names:
                        simple_name = alias.asname if alias.asname else alias.name
                        if simple_name in unused_simple_names:
                            fqn = f"{module}.{alias.name}" if module else alias.name
                            import_stmt = f"from {module} import {alias.name}"
                            if alias.asname:
                                import_stmt += f" as {alias.asname}"
                            unused_imports[fqn] = import_stmt
        
        except Exception as e:
            logging.debug(f"Could not extract import statements for {module_name}: {e}")
        
        return unused_imports
    except Exception as e:
        logging.error(f"Error getting unused imports for {module_name}: {e}")
        logging.error(traceback.format_exc())
        return {}

def _get_decorators_from_source(src: str) -> List[Dict[str, Any]]:
    """
    Extract decorators from source code with their arguments.
    
    Returns:
        List of dicts with 'name' and 'args' keys
        Example: [{'name': 'staticmethod', 'args': None}, {'name': 'app.route', 'args': "('/api')"}]
    """
    try:
        tree = ast.parse(src)
        decorators: List[Dict[str, Any]] = []
        
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                for decorator in node.decorator_list:
                    deco_info: Dict[str, Any] = {"name": "", "args": None}
                    
                    if isinstance(decorator, ast.Name):
                        # Simple decorator: @staticmethod
                        deco_info["name"] = decorator.id
                    elif isinstance(decorator, ast.Attribute):
                        # Attribute decorator: @app.route
                        parts = []
                        current = decorator
                        while isinstance(current, ast.Attribute):
                            parts.append(current.attr)
                            current = current.value
                        if isinstance(current, ast.Name):
                            parts.append(current.id)
                        deco_info["name"] = ".".join(reversed(parts))
                    elif isinstance(decorator, ast.Call):
                        # Decorator with arguments: @app.route('/api')
                        func = decorator.func
                        if isinstance(func, ast.Name):
                            deco_info["name"] = func.id
                        elif isinstance(func, ast.Attribute):
                            parts = []
                            current = func
                            while isinstance(current, ast.Attribute):
                                parts.append(current.attr)
                                current = current.value
                            if isinstance(current, ast.Name):
                                parts.append(current.id)
                            deco_info["name"] = ".".join(reversed(parts))
                        
                        # Extract arguments
                        try:
                            args_str = ast.unparse(decorator)  # Python 3.9+
                            # Remove the decorator name to get just the arguments
                            if "(" in args_str:
                                deco_info["args"] = args_str[args_str.index("("):]
                        except AttributeError:
                            # Python < 3.9 fallback
                            deco_info["args"] = "()"
                    
                    if deco_info["name"]:
                        decorators.append(deco_info)
                
                # Only process the first function/class definition
                break
        
        return decorators
    except Exception:
        return []


def find_submodules_importlib_resources(module_name: str) -> set[str]:
    """
    Discovers all submodules of a given package using importlib.resources.
    (Python 3.9+)

    Args:
        module_name (str): The name of the package to search for submodules.
    
    Returns:
        set[str]: A set of submodule names found within the package.
    """
    results: set[str] = set()
    try:
        package = importlib.import_module(module_name)
        if not isinstance(package, types.ModuleType) or not hasattr(package, '__path__'):
            return results

        package_path_traversable = importlib.resources.files(module_name)

        for item_path in package_path_traversable.iterdir():
            if item_path.is_file() and item_path.name.endswith('.py') and not item_path.name.startswith('__'):
                module_name_segment = item_path.name[:-3]
                full_module_name = f"{module_name}.{module_name_segment}"
                results.add(full_module_name)
            elif item_path.is_dir() and not item_path.name.startswith('__'):
                submodule_name_segment = item_path.name
                full_submodule_name = f"{module_name}.{submodule_name_segment}"
                # Check if it's a valid package (regular or namespace)
                spec = importlib.util.find_spec(full_submodule_name)
                if spec is not None:
                    results.add(full_submodule_name)
                    # Attempt to add nested modules as well
                    try:
                        results |= find_submodules_importlib_resources(full_submodule_name)
                    except Exception:
                        pass
    except ImportError as e:
        logging.warning(f"Warning: Could not import or process {module_name}: {e}")
    except Exception as e:
        logging.error(f"Error processing {module_name}: {e}")
    return results
