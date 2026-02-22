"""
Decorator resolution and processing utilities.

This module provides utilities for extracting decorators from source code,
resolving them to their full paths, and determining function/method labels.
"""

import ast
import inspect
import logging
from typing_extensions import Any, Callable, Dict, List, Optional, Tuple

from .source_utils import safe_get_source


def _visibility_label(name: str) -> str:
    """
    Determine visibility label for a name.
    
    Args:
        name: The name to check
        
    Returns:
        'PRIVATE', 'PROTECTED', or 'PUBLIC'
    """
    # Private: starts with __ but not dunder (not ending with __)
    if name.startswith("__") and not name.endswith("__"):
        return "PRIVATE"
    # Protected: starts with single underscore
    if name.startswith("_") and not name.startswith("__"):
        return "PROTECTED"
    return "PUBLIC"


def _get_decorators_from_source(src: str) -> List[Dict[str, Any]]:
    """
    Extract decorators from source code with their arguments.
    
    Returns:
        List of dicts with 'name' and 'args' keys
        Example: [{'name': 'staticmethod', 'args': None}, {'name': 'app.route', 'args': "('/api')"}]
    """
    try:
        tree = ast.parse(src)
        fn_node = None
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                fn_node = node
                break
        if not fn_node:
            return []
        
        decos: List[Dict[str, Any]] = []
        for d in fn_node.decorator_list:
            try:
                # Parse the full decorator expression
                full_expr = ast.unparse(d)  # type: ignore[attr-defined]
                
                # Check if it's a call (has arguments)
                if isinstance(d, ast.Call):
                    # Extract the decorator name (the function being called)
                    if isinstance(d.func, ast.Name):
                        name = d.func.id
                    elif isinstance(d.func, ast.Attribute):
                        parts = []
                        cur = d.func
                        while isinstance(cur, ast.Attribute):
                            parts.append(cur.attr)
                            cur = cur.value
                        if isinstance(cur, ast.Name):
                            parts.append(cur.id)
                        name = ".".join(reversed(parts))
                    else:
                        name = full_expr
                    
                    # Extract arguments (everything after the name)
                    args = full_expr[len(name):]  # Gets the '(...)' part
                    decos.append({'name': name, 'args': args})
                else:
                    # No arguments, just the decorator name
                    if isinstance(d, ast.Name):
                        name = d.id
                    elif isinstance(d, ast.Attribute):
                        parts = []
                        cur = d
                        while isinstance(cur, ast.Attribute):
                            parts.append(cur.attr)
                            cur = cur.value
                        if isinstance(cur, ast.Name):
                            parts.append(cur.id)
                        name = ".".join(reversed(parts))
                    else:
                        name = full_expr
                    decos.append({'name': name, 'args': None})
            except Exception:
                # Fallback for unparseable decorators
                if isinstance(d, ast.Name):
                    decos.append({'name': d.id, 'args': None})
                elif isinstance(d, ast.Attribute):
                    parts = []
                    cur = d
                    while isinstance(cur, ast.Attribute):
                        parts.append(cur.attr)
                        cur = cur.value
                    if isinstance(cur, ast.Name):
                        parts.append(cur.id)
                    decos.append({'name': ".".join(reversed(parts)), 'args': None})
                else:
                    decos.append({'name': type(d).__name__, 'args': None})
        return decos
    except Exception:
        return []


def _resolve_decorator_path(
    decorator_name: str,
    import_statements: str,
    import_as_aliases: List[Tuple[str, str]],
    current_module_path: str
) -> Optional[str]:
    """
    Resolve a decorator name to its imported path.
    
    Args:
        decorator_name: The decorator name (e.g., 'app.route', 'dataclass')
        import_statements: Raw import statements from the source
        import_as_aliases: List of (full_path, alias) tuples
        current_module_path: Full path of current module (for relative imports)
    
    Returns:
        Resolved path or None if builtin/unresolvable
    """
    # Builtin decorators don't need resolution
    BUILTINS = {'staticmethod', 'classmethod', 'property', 'abstractmethod'}
    if decorator_name in BUILTINS:
        return None
    
    # Parse the decorator name to get the base (first part before any dots)
    base_name = decorator_name.split('.')[0]
    
    # Check import aliases first (e.g., 'app' -> 'flask.Flask')
    for full_path, alias in import_as_aliases:
        if alias == base_name:
            # Replace the base with the full path
            remaining = decorator_name[len(base_name):]
            return full_path + remaining
    
    # Try to find in import statements
    try:
        tree = ast.parse(import_statements)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for alias in node.names:
                    # Check if this import matches our base name
                    imported_name = alias.asname if alias.asname else alias.name
                    if imported_name == base_name:
                        # Found it! Build the full path
                        full_path = f"{module}.{alias.name}" if module else alias.name
                        remaining = decorator_name[len(base_name):]
                        return full_path + remaining
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    imported_name = alias.asname if alias.asname else alias.name
                    if imported_name == base_name:
                        # Direct import
                        remaining = decorator_name[len(base_name):]
                        return alias.name + remaining
    except Exception as e:
        logging.debug(f"Failed to resolve decorator {decorator_name}: {e}")
    
    # If not found in imports, might be defined in current module
    return f"{current_module_path}.{decorator_name}"


def _resolve_decorator_details(
    decorators: List[Dict[str, Any]],
    import_statements: str,
    import_as_aliases: List[Tuple[str, str]],
    import_details: Optional[Dict],
    current_module_path: str
) -> List[Dict[str, Any]]:
    """
    Resolve decorators to their full paths and versions.
    
    Args:
        decorators: List of decorator dicts with 'name' and 'args'
        import_statements: Raw import statements
        import_as_aliases: List of (full_path, alias) tuples
        import_details: Parsed import details with version info
        current_module_path: Current module path for local decorators
        
    Returns:
        List of decorator dicts with added 'resolved_path' and 'version'
    """
    resolved_decorators = []
    
    for deco in decorators:
        deco_name = deco['name']
        deco_args = deco.get('args')
        
        # Try to resolve the decorator path
        resolved_path = _resolve_decorator_path(
            deco_name, import_statements, import_as_aliases, current_module_path
        )
        
        # Try to get version if resolved to an external module
        version = None
        if resolved_path and import_details:
            # Extract root module from resolved path
            root_module = resolved_path.split('.')[0]
            # Look for version in import_details
            modules_dict = import_details.get('modules', {})
            if root_module in modules_dict:
                version = modules_dict[root_module].get('version')
        
        resolved_decorators.append({
            'name': deco_name,
            'args': deco_args,
            'resolved_path': resolved_path,
            'version': version
        })
    
    return resolved_decorators


def get_function_method_labels(func: Callable, name: str) -> Tuple[List[str], List[Dict[str, Any]]]:
    """
    Determine extra labels and decorators list.
    Only returns ASYNC, GENERATOR, and visibility labels for main entity.
    Decorator-specific labels (PROPERTY, CLASSMETHOD, STATICMETHOD) should NOT be returned
    as they are source-specific and stored in DECORATOR_DETAILS entity.
    Returns (labels, decorators) where decorators is a list of dicts with 'name' and 'args'
    """
    labels: List[str] = []
    # Async / generator - these are intrinsic to the function, not source-specific
    if inspect.iscoroutinefunction(func) or inspect.isasyncgenfunction(func):
        labels.append("ASYNC")
    if inspect.isgeneratorfunction(func):
        labels.append("GENERATOR")

    # Decorators from source - collect for DECORATOR_DETAILS entity
    decorators: List[Dict[str, Any]] = []
    try:
        src = safe_get_source(func)
        decorators = _get_decorators_from_source(src)
    except Exception:
        pass

    # Visibility
    labels.append(_visibility_label(name))
    return labels, decorators
