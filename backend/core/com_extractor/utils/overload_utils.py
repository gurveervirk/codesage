"""
Overload extraction utilities for Python versions before 3.11.

This module provides AST-based overload detection for Python versions that don't
have typing_extensions.get_overloads() or when it fails to detect overloads.
It extracts @overload decorated functions from source code using AST parsing.
"""

import ast
import inspect
import logging
import sys
from typing import Any, Callable, List, Optional, Set
from typing_extensions import get_overloads


def _is_overload_decorator(decorator: ast.expr) -> bool:
    """
    Check if an AST decorator node represents @overload.
    
    Handles various forms:
    - @overload
    - @typing.overload
    - @typing_extensions.overload
    """
    if isinstance(decorator, ast.Name):
        return decorator.id == "overload"
    elif isinstance(decorator, ast.Attribute):
        if decorator.attr == "overload":
            # Check if it's typing.overload or typing_extensions.overload
            if isinstance(decorator.value, ast.Name):
                return decorator.value.id in ("typing", "typing_extensions")
    return False


def _extract_function_from_module(
    module: Any,
    func_name: str,
    qualname: str,
    decorator_list: List[ast.expr]
) -> Optional[Callable]:
    """
    Try to extract a function object from a module given its name and qualname.
    
    Args:
        module: The module object
        func_name: Simple function name
        qualname: Qualified name (e.g., 'ClassName.method_name')
        decorator_list: List of decorators from AST (to verify it's an overload)
        
    Returns:
        The function object if found, None otherwise
    """
    try:
        # Simple case: top-level function
        if "." not in qualname:
            obj = getattr(module, func_name, None)
            if callable(obj):
                return obj
            return None
        
        # Nested case: method or nested function
        parts = qualname.split(".")
        obj = module
        
        for part in parts[:-1]:
            obj = getattr(obj, part, None)
            if obj is None:
                return None
        
        # Get the final function/method
        func = getattr(obj, parts[-1], None)
        if callable(func):
            return func
        
        return None
    except Exception as e:
        logging.debug(f"Could not extract function {qualname} from module: {e}")
        return None


def extract_overloads_from_ast(obj: Callable) -> List[Callable]:
    """
    Extract @overload decorated variants of a function using AST parsing.
    
    This is a fallback for Python < 3.11 or when typing_extensions.get_overloads()
    fails. It parses the source file to find all @overload decorated functions
    with the same name/qualname.
    
    Args:
        obj: The function/method object to find overloads for
        
    Returns:
        List of overload function objects (may be empty)
    """
    try:
        # Get source file and module
        source_file = inspect.getsourcefile(obj)
        if not source_file:
            return []
        
        module = inspect.getmodule(obj)
        if not module:
            return []
        
        # Read source code
        with open(source_file, 'r', encoding='utf-8') as f:
            source = f.read()
        
        # Parse AST
        try:
            tree = ast.parse(source, filename=source_file)
        except SyntaxError:
            return []
        
        # Get object's qualname for matching
        obj_qualname = getattr(obj, '__qualname__', None)
        obj_name = getattr(obj, '__name__', None)
        
        if not obj_name:
            return []
        
        overload_funcs: List[Callable] = []
        
        # Walk the AST to find overload decorators
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            
            # Check if function name matches
            if node.name != obj_name:
                continue
            
            # Check if it has @overload decorator
            has_overload = any(_is_overload_decorator(dec) for dec in node.decorator_list)
            if not has_overload:
                continue
            
            # Try to construct qualname for this node
            # This is approximate - we look for the function in the module
            # Note: For methods, we need to account for class nesting
            node_qualname = _construct_qualname_from_ast(tree, node)
            
            # Skip if qualnames don't match (different scope)
            if obj_qualname and node_qualname and obj_qualname != node_qualname:
                # Check if it's at least in the same class
                if not obj_qualname.endswith(f".{obj_name}") or not node_qualname.endswith(f".{obj_name}"):
                    continue
            
            # Try to extract the actual function object
            # Note: This is tricky because @overload decorated functions
            # might not be directly accessible in the runtime
            func = _extract_function_from_module(module, node.name, node_qualname or node.name, node.decorator_list)
            
            if func and func is not obj:  # Don't include the implementation
                overload_funcs.append(func)
        
        return overload_funcs
        
    except Exception as e:
        logging.debug(f"Failed to extract overloads from AST for {obj}: {e}")
        return []


def _construct_qualname_from_ast(tree: ast.Module, target_node: ast.FunctionDef) -> Optional[str]:
    """
    Construct a qualified name for a function node by walking the AST.
    
    This attempts to build the qualname by finding parent classes.
    """
    # Map each node to its parent
    parent_map = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parent_map[child] = node
    
    # Walk up from target_node to build qualname
    parts = [target_node.name]
    current = target_node
    
    while current in parent_map:
        parent = parent_map[current]
        if isinstance(parent, ast.ClassDef):
            parts.insert(0, parent.name)
        elif isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Nested function
            parts.insert(0, parent.name)
        current = parent
    
    return ".".join(parts) if len(parts) > 1 else parts[0]


def get_overloads_with_fallback(obj: Callable) -> List[Callable]:
    """
    Get overloads for a function/method with fallback to AST extraction.
    
    First tries typing_extensions.get_overloads() (Python 3.11+),
    then falls back to AST-based extraction for older versions.
    
    Args:
        obj: The function/method to get overloads for
        
    Returns:
        List of overload function objects
    """
    # Try the standard way first (Python 3.11+)
    try:
        overloads = get_overloads(obj)
        if overloads:
            logging.debug(f"Found {len(overloads)} overloads using get_overloads() for {obj}")
            return list(overloads)
    except Exception as e:
        logging.debug(f"get_overloads() failed for {obj}: {e}")
    
    # Fallback to AST extraction
    python_version = sys.version_info
    if python_version < (3, 11):
        logging.debug(f"Python {python_version.major}.{python_version.minor} detected, using AST fallback for overloads")
        overloads = extract_overloads_from_ast(obj)
        if overloads:
            logging.debug(f"Found {len(overloads)} overloads using AST extraction for {obj}")
            return overloads
    
    return []


def get_overload_signatures_from_source(obj: Callable) -> List[str]:
    """
    Extract raw signature strings for all @overload variants from source.
    
    This extracts just the signature strings without needing the callable objects,
    which is useful when the overload functions aren't accessible at runtime.
    
    Args:
        obj: The function/method to find overload signatures for
        
    Returns:
        List of unique signature strings (e.g., ['(x: int) -> int', '(x: str) -> str'])
    """
    try:
        # Get source file
        source_file = inspect.getsourcefile(obj)
        if not source_file:
            return []
        
        # Read source code
        with open(source_file, 'r', encoding='utf-8') as f:
            source = f.read()
        
        # Parse AST
        try:
            tree = ast.parse(source, filename=source_file)
        except SyntaxError:
            return []
        
        # Get object's name and qualname
        obj_name = getattr(obj, '__name__', None)
        if not obj_name:
            return []
        
        obj_qualname = getattr(obj, '__qualname__', obj_name)
        
        signatures_set: Set[str] = set()
        
        # Walk the AST to find overload decorators
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            
            # Check if function name matches
            if node.name != obj_name:
                continue
            
            # Check if it has @overload decorator
            has_overload = any(_is_overload_decorator(dec) for dec in node.decorator_list)
            if not has_overload:
                continue
            
            # Construct qualname for this node to ensure we're matching the right function
            node_qualname = _construct_qualname_from_ast(tree, node)
            
            # Only include if qualnames match (same scope/class)
            if obj_qualname and node_qualname:
                if obj_qualname != node_qualname:
                    # For methods, check if at least the class context matches
                    obj_parts = obj_qualname.split('.')
                    node_parts = node_qualname.split('.')
                    
                    # Skip if not in same class or different nesting
                    if len(obj_parts) != len(node_parts):
                        continue
                    if obj_parts[:-1] != node_parts[:-1]:
                        continue
            
            # Extract signature from AST
            sig_str = _extract_signature_from_ast_node(node)
            if sig_str:
                signatures_set.add(sig_str)
        
        # Return as sorted list for consistency
        return sorted(signatures_set)
        
    except Exception as e:
        logging.debug(f"Failed to extract overload signatures from source for {obj}: {e}")
        return []


def _extract_signature_from_ast_node(node: ast.FunctionDef) -> Optional[str]:
    """
    Extract signature string from AST FunctionDef node.
    
    Builds a signature string like '(x: int, y: str) -> bool' from AST.
    """
    try:
        args = node.args
        params = []
        
        # Regular args
        for i, arg in enumerate(args.args):
            param_str = arg.arg
            if arg.annotation:
                param_str += f": {ast.unparse(arg.annotation)}"
            
            # Check for defaults
            defaults_offset = len(args.args) - len(args.defaults)
            if i >= defaults_offset:
                default_idx = i - defaults_offset
                param_str += f" = {ast.unparse(args.defaults[default_idx])}"
            
            params.append(param_str)
        
        # *args
        if args.vararg:
            param_str = f"*{args.vararg.arg}"
            if args.vararg.annotation:
                param_str += f": {ast.unparse(args.vararg.annotation)}"
            params.append(param_str)
        
        # **kwargs
        if args.kwarg:
            param_str = f"**{args.kwarg.arg}"
            if args.kwarg.annotation:
                param_str += f": {ast.unparse(args.kwarg.annotation)}"
            params.append(param_str)
        
        # Build signature
        sig = f"({', '.join(params)})"
        
        # Add return annotation
        if node.returns:
            sig += f" -> {ast.unparse(node.returns)}"
        
        return sig
        
    except Exception as e:
        logging.debug(f"Failed to extract signature from AST node: {e}")
        return None
