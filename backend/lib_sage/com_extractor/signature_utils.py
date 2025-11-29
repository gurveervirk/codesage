"""
Type resolution and signature handling utilities.

This module provides utilities for extracting type hints, resolving signatures,
and building namespaces from Python source code using AST analysis.
"""

import ast
import builtins
import importlib
import inspect
import logging
import re
import types
import typing
from typing import Any, Callable, Dict, List, Optional, Tuple
from typing_extensions import get_overloads, get_type_hints, Literal


# Module cache for namespace resolution
module_cache: Dict[str, Any] = {}


def create_mock_typeshed_module():
    """Create a mock _typeshed module that can be used in the namespace."""
    mock_module = types.ModuleType("_typeshed")
    mock_module.__file__ = "<_typeshed>"
    return mock_module


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


def _owner_class_of_callable(func: Callable) -> Optional[type]:
    """Try to recover the owning class for a method/function by walking its qualname within the module."""
    try:
        # If the function has a __self__ attribute, it is a bound method
        if hasattr(func, "__self__"):
            return func.__self__.__class__
        # Otherwise, attempt to recover the class by walking __qualname__
        qualname = getattr(func, "__qualname__", "")
        if "." not in qualname:
            return None
        # Potential class name
        class_path = ".".join(qualname.split(".")[:-1])
        mod = inspect.getmodule(func)
        if mod is None:
            return None
        obj = mod
        for part in class_path.split("."):
            obj = getattr(obj, part, None)
            if obj is None:
                return None
        if inspect.isclass(obj):
            return obj
        return None
    except Exception:
        return None


def get_namespaces(source: str, module: Any) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """
    Parses the source code to extract import statements and assignments, especially those inside blocks.
    Uses `ast` to safely parse the code without executing it.
    Uses `inspect` to assign values to the imported names and assigned variables.
    Most importantly, this only captures those assignments that define types, not function calls or other similar constructs.
    Handles both absolute and relative imports.
    Now also captures TypeVar and Callable assignments.
    """
    # Check module cache
    mod_name = getattr(module, "__name__", None)
    if mod_name and mod_name in module_cache:
        cached_ns, cached_runtime_ns = module_cache[mod_name]
        return cached_ns, cached_runtime_ns

    tree = ast.parse(source)
    namespace: Dict[str, Any] = {}
    runtime_ns: Dict[str, str] = {}

    # Try importing the module to get its runtime context
    try:
        if module is not None and hasattr(module, "__dict__"):
            namespace.update(module.__dict__)
    except Exception:
        pass

    # Create a mock _typeshed module to prevent import errors
    mock_typeshed = create_mock_typeshed_module()
    namespace["_typeshed"] = mock_typeshed

    def is_type_like(node: ast.AST) -> bool:
        """Heuristically determine if an AST node represents a type expression or a TypeVar assignment."""
        if isinstance(node, (ast.Name, ast.Attribute)):
            return True
        if isinstance(node, ast.Subscript):
            return is_type_like(node.value) and is_type_like(node.slice) if hasattr(node, "slice") else True
        if isinstance(node, (ast.Tuple, ast.List)):
            return all(is_type_like(elt) for elt in node.elts)
        if isinstance(node, ast.Dict):
            return all(is_type_like(k) and is_type_like(v) for k, v in zip(node.keys, node.values) if k is not None and v is not None)
        if isinstance(node, (ast.Constant, ast.Constant)):  # for Optional[None], Literal values ignored here
            return True
        if isinstance(node, ast.Index):  # py<3.9
            return is_type_like(node.value)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):  # PEP 604 union types
            return is_type_like(node.left) and is_type_like(node.right)
        # NEW: Accept ast.Call if it is a TypeVar call
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "TypeVar":
                return True
            if isinstance(func, ast.Attribute) and func.attr == "TypeVar":
                return True
        return False

    def resolve_relative_import(module, level, from_module):
        if not hasattr(module, "__name__"):
            return None
        base = module.__name__.split(".")
        if "__init__" in base:
            base.remove("__init__")
        if level > 0:
            base = base[:-(level)] if level <= len(base) else []
        if from_module:
            base.append(from_module)
        return ".".join([b for b in base if b])

    def is_typeshed_module(name: Optional[str]) -> bool:
        if not name:
            return False
        parts = name.split(".")
        return bool(parts) and parts[-1] == "_typeshed"

    def resolve_typevar_to_bound(obj: Any) -> Any:
        """If obj is a TypeVar, resolve to its bound, constraints, or Any. Otherwise return obj."""
        try:
            if isinstance(obj, typing.TypeVar):
                tv = obj
                if tv.__bound__ is not None:
                    logging.info(f"TypeVar {tv} resolved to bound {tv.__bound__}")
                    return tv.__bound__
                if tv.__constraints__:
                    if len(tv.__constraints__) == 1:
                        logging.info(f"TypeVar {tv} resolved to single constraint {tv.__constraints__[0]}")
                        return tv.__constraints__[0]
                    try:
                        union_t = typing.Union[tuple(tv.__constraints__)]  # type: ignore[index]
                    except Exception:
                        union_t = typing.Any
                    logging.info(f"TypeVar {tv} resolved to Union{tv.__constraints__} -> {union_t}")
                    return union_t
                logging.info(f"TypeVar {tv} has no bound/constraints; defaulting to Any")
                return typing.Any
        except Exception:
            pass
        return obj
    
    class ClassDefVisitor(ast.NodeVisitor):
        def visit_ClassDef(self, node: ast.ClassDef):
            # Pick only those classes that are supposed to be parsed by Type Checkers and Linters (TYPE_CHECKING | MYPY)
            # We consider classes that do NOT exist at runtime on the module (e.g., defined under TYPE_CHECKING)
            try:
                mod_name = getattr(module, "__name__", "")
                existing = getattr(module, node.name, None) if module is not None else None
                if existing is None:
                    logging.info(f"Class {node.name} not found in module {mod_name}; assuming TYPE_CHECKING-only class")
                    full_name = f"{mod_name}.{node.name}" if mod_name else node.name
                    runtime_ns[node.name] = full_name
                    namespace[node.name] = full_name  # Placeholder to acknowledge presence
                    if mod_name:
                        namespace[mod_name] = module  # Ensure module is also in namespace
            except Exception:
                pass
            self.generic_visit(node)

    class ImportVisitor(ast.NodeVisitor):
        def visit_Import(self, node: ast.Import):
            for alias in node.names:
                is_runtime_name = False
                name = alias.asname or alias.name.split(".")[-1]
                # Attempt to import and bind the actual object (module)
                try:
                    imported = importlib.import_module(alias.name)
                except Exception:
                    logging.warning(f"Failed to import module: {alias.name}")
                    imported = name
                    is_runtime_name = True
                
                if is_runtime_name:
                    runtime_ns[name] = imported
                    namespace[name] = imported  # Placeholder to acknowledge presence
                else:
                    namespace[name] = imported
            self.generic_visit(node)

        def visit_ImportFrom(self, node: ast.ImportFrom):
            module_name = node.module or ""
            level = getattr(node, "level", 0) or 0
            abs_mod_name = module_name
            if level > 0:
                abs_mod_name = resolve_relative_import(module, level, module_name)
            # Special-case: any attempt to import from _typeshed -> map each imported symbol to "_typeshed.<name>"
            if is_typeshed_module(abs_mod_name or module_name):
                for alias in node.names:
                    if alias.name == "*":
                        # We cannot expand star import from _typeshed; skip but note
                        logging.info("Ignoring star import from _typeshed; cannot enumerate names")
                        continue
                    as_name = alias.asname or alias.name
                    mapped = f"_typeshed.{alias.name}"
                    runtime_ns[as_name] = mapped
                    
                    # Create a mock attribute on _typeshed module
                    # This allows get_type_hints to resolve _typeshed.X without importing
                    setattr(mock_typeshed, alias.name, mapped)
                    namespace[as_name] = mapped

                    # Also, map the actual name in runtime_ns and namespace to `mapped`
                    runtime_ns[alias.name] = mapped
                    setattr(mock_typeshed, alias.name, mapped)
                    namespace[alias.name] = mapped
                    logging.info(f"Mapped from-import of _typeshed: {alias.name} as {as_name} -> '{mapped}' (mock created)")
                self.generic_visit(node)
                return
            for alias in node.names:
                as_name = alias.asname or alias.name
                bound = None
                is_runtime_name = False
                mod = None
                # Attempt to import and bind the actual object (attribute from module)
                if abs_mod_name:
                    try:
                        mod = importlib.import_module(abs_mod_name)
                        bound = getattr(mod, alias.name, None)
                        if bound is None:
                            logging.warning(f"Name {alias.name} not found in module {abs_mod_name}. Binding to string placeholder.")
                            # Assign bound to mod.alias.name, as str, to indicate presence
                            is_runtime_name = True
                            bound = f"{mod.__name__}.{alias.name}"
                        else:
                            logging.info(f"Imported from {abs_mod_name}: {alias.name} as {as_name} -> {bound}")
                    except Exception as e:
                        logging.warning(f"Failed to import from module: {abs_mod_name}, name: {alias.name} with error: {e}")
                        bound = None
                else:
                    # relative or unknown - leave as None
                    logging.info(f"Relative or unknown import: from {module_name} import {alias.name}")
                    bound = None
                
                if is_runtime_name:
                    runtime_ns[as_name] = bound
                    namespace[as_name] = bound  # Placeholder to acknowledge presence
                    if mod is not None:
                        namespace[mod.__name__] = mod  # Ensure module is also in namespace
                else:
                    namespace[as_name] = bound
            self.generic_visit(node)

    class AssignVisitor(ast.NodeVisitor):
        def __init__(self):
            super().__init__()
            self._fn_depth = 0  # track if we are inside a function/method definition

        # Track entering/leaving function/method scopes
        def visit_FunctionDef(self, node: ast.FunctionDef):
            self._fn_depth += 1
            self.generic_visit(node)
            self._fn_depth -= 1

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
            self._fn_depth += 1
            self.generic_visit(node)
            self._fn_depth -= 1

        def visit_Assign(self, node: ast.Assign):
            # Only capture simple name targets and type-like RHS (including TypeVar)
            if is_type_like(node.value):
                safe_ns: Dict[str, Any] = {
                    "typing": typing,
                    "builtins": builtins,
                }
                # Provide a placeholder for _typeshed to help eval guarded code gracefully
                safe_ns.setdefault("_typeshed", "_typeshed")
                safe_ns.update(namespace)
                try:
                    rhs = ast.unparse(node.value)  # py>=3.9
                except Exception:
                    logging.warning(f"Failed to unparse assignment RHS at line {node.lineno}")
                    rhs = None
                value_obj: Any = None
                if rhs is not None:
                    try:
                        value_obj = eval(rhs, safe_ns, {})
                    except Exception as e:
                        logging.debug(f"Failed to eval assignment RHS: {rhs} at line {node.lineno} with error: {e}")
                        value_obj = None
                # If this is a TypeVar object, resolve to its bound/constraints
                value_obj = resolve_typevar_to_bound(value_obj)
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        namespace[target.id] = value_obj
                        if isinstance(value_obj, typing.TypeVar):
                            logging.info(f"Assigned TypeVar {target.id} as {value_obj}")
                        else:
                            logging.debug(f"Assigned {target.id} = {value_obj}")
            else:
                # Special case: TypeVar assignment (ast.Call to TypeVar)
                if isinstance(node.value, ast.Call):
                    func = node.value.func
                    is_typevar = False
                    if isinstance(func, ast.Name) and func.id == "TypeVar":
                        is_typevar = True
                    if isinstance(func, ast.Attribute) and func.attr == "TypeVar":
                        is_typevar = True
                    if is_typevar:
                        safe_ns: Dict[str, Any] = {
                            "typing": typing,
                            "builtins": builtins,
                        }
                        safe_ns.setdefault("_typeshed", "_typeshed")
                        safe_ns.update(namespace)
                        try:
                            rhs = ast.unparse(node.value)
                        except Exception:
                            rhs = None
                        value_obj: Any = None
                        if rhs is not None:
                            try:
                                value_obj = eval(rhs, safe_ns, {})
                            except Exception:
                                value_obj = None
                        # Resolve TypeVar to its bound/constraints before storing
                        value_obj = resolve_typevar_to_bound(value_obj)
                        for target in node.targets:
                            if isinstance(target, ast.Name):
                                namespace[target.id] = value_obj
                                logging.info(f"Resolved TypeVar assignment: {target.id} -> {value_obj}")
                logging.debug(f"Ignoring non-type-like assignment at line {node.lineno}")
            self.generic_visit(node)

        def visit_AnnAssign(self, node: ast.AnnAssign):
            target = node.target
            if isinstance(target, ast.Name):
                value_obj: Any = None
                if node.value and is_type_like(node.value):
                    try:
                        rhs = ast.unparse(node.value)
                    except Exception:
                        rhs = None
                    if rhs is not None:
                        try:
                            safe_ns = {"typing": typing, "builtins": builtins}
                            safe_ns.setdefault("_typeshed", "_typeshed")
                            safe_ns.update(namespace)
                            value_obj = eval(rhs, safe_ns, {})
                        except Exception:
                            value_obj = None
                # Resolve if the evaluated value is a TypeVar
                value_obj = resolve_typevar_to_bound(value_obj)
                namespace[target.id] = value_obj
                if isinstance(value_obj, typing.TypeVar):
                    logging.info(f"Annotated assign TypeVar {target.id} as {value_obj}")
            logging.debug(f"Ignoring non-name annotated assignment at line {node.lineno}")
            self.generic_visit(node)

        def visit_AugAssign(self, node: ast.AugAssign):
            target = node.target
            if isinstance(target, ast.Name):
                namespace[target.id] = None
            self.generic_visit(node)

    class FunctionSignatureStrResolver(ast.NodeVisitor):
        """
        Resolve forward-ref/string annotations used in function and method signatures by
        ensuring base modules/names referenced in the annotation strings are imported/bound
        into the namespace. This avoids generic dotted-name resolution elsewhere.
        """
        def __init__(self, module: Any):
            self.module = module

        def _ensure_import(self, base_name: str) -> None:
            if not base_name:
                return
            if base_name in ("typing", "builtins"):
                return
            if base_name in namespace:
                return
            try:
                imported = importlib.import_module(base_name)
                namespace[base_name] = imported
            except Exception:
                # As a conservative fallback, bind to its string name as a placeholder
                runtime_ns[base_name] = base_name
                namespace[base_name] = base_name

        def _process_annotation_str(self, ann_str: str) -> None:
            try:
                expr = ast.parse(ann_str, mode="eval")
            except Exception:
                return

            base_names: set[str] = set()

            def collect_bases(node: ast.AST) -> None:
                if isinstance(node, ast.Attribute):
                    cur = node
                    while isinstance(cur, ast.Attribute):
                        cur = cur.value
                    if isinstance(cur, ast.Name):
                        base_names.add(cur.id)
                elif isinstance(node, ast.Name):
                    base_names.add(node.id)
                elif isinstance(node, ast.Subscript):
                    collect_bases(node.value)
                    sl = getattr(node, "slice", None)
                    if sl is None:
                        return
                    def walk_slice(s: ast.AST) -> None:
                        if isinstance(s, ast.Name):
                            base_names.add(s.id)
                        elif isinstance(s, ast.Attribute):
                            cur2 = s
                            while isinstance(cur2, ast.Attribute):
                                cur2 = cur2.value
                            if isinstance(cur2, ast.Name):
                                base_names.add(cur2.id)
                        elif isinstance(s, ast.Tuple):
                            for e in s.elts:
                                walk_slice(e)
                        elif isinstance(s, ast.Subscript):
                            collect_bases(s)
                        elif hasattr(ast, "Index") and isinstance(s, ast.Index):  # py<3.9
                            walk_slice(s.value)
                    walk_slice(sl)
                elif isinstance(node, ast.Call):
                    collect_bases(node.func)
                    for a in getattr(node, "args", []) or []:
                        collect_bases(a)
                    for kw in getattr(node, "keywords", []) or []:
                        collect_bases(getattr(kw, "value", None) or ast.Constant(value=None))
                if node is not None:
                    for child in ast.iter_child_nodes(node):
                        collect_bases(child)

            collect_bases(expr.body)
            for base in list(base_names):
                self._ensure_import(base)

        def _process_annotation(self, ann: ast.AST) -> None:
            s: Optional[str] = None
            if isinstance(ann, ast.Constant) and isinstance(ann.value, str):
                s = ann.value
            elif hasattr(ast, "Str") and isinstance(ann, ast.Str):  # py<3.8
                s = ann.s  # type: ignore[attr-defined]
            if s:
                self._process_annotation_str(s)

        def _process_args(self, args: ast.arguments) -> None:
            for arg in getattr(args, "posonlyargs", []) or []:
                if getattr(arg, "annotation", None) is not None:
                    self._process_annotation(arg.annotation)
            for arg in getattr(args, "args", []) or []:
                if getattr(arg, "annotation", None) is not None:
                    self._process_annotation(arg.annotation)
            if getattr(args, "vararg", None) is not None and getattr(args.vararg, "annotation", None) is not None:
                self._process_annotation(args.vararg.annotation)
            for arg in getattr(args, "kwonlyargs", []) or []:
                if getattr(arg, "annotation", None) is not None:
                    self._process_annotation(arg.annotation)
            if getattr(args, "kwarg", None) is not None and getattr(args.kwarg, "annotation", None) is not None:
                self._process_annotation(args.kwarg.annotation)

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            if getattr(node, "returns", None) is not None:
                self._process_annotation(node.returns)
            self._process_args(getattr(node, "args", ast.arguments()))
            self.generic_visit(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self.visit_FunctionDef(node)

    ClassDefVisitor().visit(tree)
    ImportVisitor().visit(tree)
    AssignVisitor().visit(tree)
    # Resolve forward-ref/string annotations in function/method signatures
    FunctionSignatureStrResolver(module).visit(tree)

    # Cache module results
    if mod_name:
        module_cache[mod_name] = (namespace, runtime_ns)
    return namespace, runtime_ns


def get_globals(func: Callable) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Retrieve the global namespace for a function, including its module and function globals."""
    globalns: Dict[str, Any] = {}
    runtime_ns: Dict[str, str] = {}
    try:
        mod = inspect.getmodule(func)
        logging.info(f"Inspecting module: {getattr(mod, '__name__', 'unknown')}")
        if mod is not None:
            globalns = dict(getattr(mod, "__dict__", {}))

            # Use `ast` to parse the owning module's source code, to get imports and assignments that may have been missed out
            try:
                source = inspect.getsource(mod)
                parsed_ns, runtime_ns = get_namespaces(source, mod)
                # Merge parsed types/imports into globals without re-evaluating
                for name, val in parsed_ns.items():
                    if name not in globalns and val is not None:
                        globalns[name] = val
            except Exception as e:
                logging.warning(f"Error parsing imports and assignments: {e}")
                pass
        # For functions, __globals__ is also useful
        if hasattr(func, "__globals__") and isinstance(func.__globals__, dict):
            merged = dict(globalns)
            merged.update(func.__globals__)
            globalns = merged
    except Exception:
        pass

    # Convert stuff from runtime_ns to Literal placeholders in globals
    for name in runtime_ns.keys():
        globalns[name] = Literal[runtime_ns[name]] # Placeholder to acknowledge presence

    return globalns, runtime_ns


def get_typed_signature(func, include_overloads: bool = True):
    """
    Build a readable, type-resolved signature string for a callable.
    If typing overloads exist for the callable, include each overload's resolved signature
    followed by the implementation signature.
    """

    def _compute_single_signature(fn: Callable) -> str:
        # If fn is a class, use __init__ for type hints resolution
        # but keep the original fn for signature (inspect.signature handles this internally)
        target_for_hints = fn
        if inspect.isclass(fn):
            if hasattr(fn, '__init__'):
                target_for_hints = fn.__init__
                logging.info(f"Function is a class; using __init__ for type hints resolution")
        
        sig = inspect.signature(fn)
        logging.info(f"Inspecting signature for function: {fn.__name__}{sig}")

        typed_params: list[inspect.Parameter] = []

        # Get globals, locals and runtime namespace for type hint resolution
        globalns: Dict[str, Any] = {}
        localns: Dict[str, Any] = {}
        runtime_ns: Dict[str, str] = {}

        try:
            mod = inspect.getmodule(target_for_hints)
            if mod is not None:
                globalns = dict(getattr(mod, "__dict__", {}))
                logging.info("Successfully retrieved module globals.")

                # Use `ast` to parse the owning module's source code, to get imports and assignments that may have been missed out
                try:
                    source = inspect.getsource(mod)
                    parsed_ns, runtime_ns = get_namespaces(source, mod)
                    logging.info("Received parsed namespace keys: %s", list(parsed_ns.keys()))
                    for name, val in parsed_ns.items():
                        if name not in globalns and val is not None:
                            globalns[name] = val
                except Exception as e:
                    logging.warning(f"Error parsing imports and assignments: {e}")
                    pass
                logging.info("Successfully parsed imports and assignments from source.")
            else:
                logging.warning("Could not retrieve module; using empty globals.")

            # For functions, __globals__ is also useful
            if hasattr(fn, "__globals__") and isinstance(fn.__globals__, dict):
                # Prefer function globals but merge with module dict to be safe
                merged = dict(globalns)
                merged.update(fn.__globals__)
                globalns = merged
                logging.info("Successfully merged function globals.")
            # Attempt to get the owner class for methods to access class-level annotations
            owner_cls = _owner_class_of_callable(target_for_hints)
            if owner_cls is not None:
                localns = dict(vars(owner_cls))
        except Exception as e:
            logging.warning(f"Error occurred while retrieving type hints: {e}")

        # Ensure the root package of the function's module is available in globals (e.g., 'pydantic')
        try:
            mod_name = getattr(inspect.getmodule(target_for_hints), "__name__", "")
            root_mod = mod_name.split(".")[0] if mod_name else ""
            if root_mod and root_mod not in globalns:
                try:
                    globalns[root_mod] = importlib.import_module(root_mod)
                except Exception as e:
                    logging.warning(f"Failed to import root module: {root_mod}, error: {e}")
                    pass
        except Exception as e:
            logging.warning(f"Error occurred while ensuring root module is available: {e}")
            pass

        type_hints = {}
        retries = 0
        while retries < 10:
            try:
                type_hints = get_type_hints(target_for_hints, globalns=globalns, localns=localns)
                break
            except AttributeError as e:
                # In Python 3.9/3.13, get_type_hints can raise AttributeError while resolving forward refs
                error_msg = str(e)
                missing_attr = getattr(e, 'name', None)
                base_obj = getattr(e, 'obj', None)

                if missing_attr is None or base_obj is None:
                    if "has no attribute" in error_msg:
                        logging.warning(f"Skipping type hints due to AttributeError during forward ref evaluation: {e}")
                        return str(sig)
                    raise
                
                try:
                    base_name = getattr(base_obj, '__name__', base_obj.__class__.__name__)
                except Exception:
                    base_name = '<unknown>'
                missing_name = f"{base_name}.{missing_attr}"
                placeholder = typing.Literal[missing_name]
                
                # Only try to set attribute if base_obj has a __dict__ (is a module, class, or instance)
                # Cannot set attributes on built-in types like str, int, etc.
                can_set_attr = hasattr(base_obj, '__dict__') or hasattr(type(base_obj), '__dict__')
                
                try:
                    if can_set_attr:
                        setattr(base_obj, missing_attr, placeholder)
                    # Always add to namespaces even if we can't set on the object
                    globalns[missing_name] = placeholder
                    localns[missing_name] = placeholder
                    runtime_ns[missing_name] = missing_name
                    logging.info(f"Injected placeholder for missing attribute: {base_name}.{missing_attr} -> Literal['{base_name}.{missing_attr}']")
                except (AttributeError, TypeError) as set_error:
                    # If we cannot set attribute on the object, just add to namespaces and continue
                    # This handles cases like frozen classes, built-in types, etc.
                    logging.debug(f"Could not set attribute on {base_name}, but added to namespaces: {set_error}")
                    globalns[missing_name] = placeholder
                    localns[missing_name] = placeholder
                    runtime_ns[missing_name] = missing_name
            except TypeError as e:
                error_msg = str(e)
                if "not subscriptable" in error_msg or "unsupported operand type" in error_msg:
                    logging.warning(f'Skipping type hints due to TypeError (likely malformed annotation): {e}')
                    return str(sig)  # Fallback to raw signature
                # Re-raise other TypeErrors
                raise
            except NameError as e:
                # Skip getting type hints if Name Error is thrown
                logging.info(f'Skipping getting type hints due to NameError: {e}')
                return str(sig)  # Fallback to raw signature
            except Exception:
                # Propagate other exceptions
                raise
            retries += 1

        for name, param in sig.parameters.items():
            annotation = type_hints.get(name, param.annotation)
            typed_params.append(param.replace(annotation=annotation))

        return_type = type_hints.get("return", sig.return_annotation)

        typed_signature = str(sig.replace(parameters=typed_params, return_annotation=return_type))

        # If we have a runtime namespace, we can use it for more accurate type hint resolution. Simply replace the `Literal` placeholders with their actual runtime values.
        if runtime_ns:
            # Replace any str type hints with their runtime resolved values if available
            while True:
                at_least_one_resolved = False
                # As runtime_ns maps names to str representations, we can only resolve direct matches
                for _, str_repr in runtime_ns.items():
                    if f"typing.Literal['{str_repr}']" in typed_signature:
                        typed_signature = typed_signature.replace(f"typing.Literal['{str_repr}']", str_repr)
                        at_least_one_resolved = True
                    elif f'typing.Literal["{str_repr}"]' in typed_signature:
                        typed_signature = typed_signature.replace(f'typing.Literal["{str_repr}"]', str_repr)
                        at_least_one_resolved = True
                    elif f'Literal["{str_repr}"]' in typed_signature:
                        typed_signature = typed_signature.replace(f'Literal["{str_repr}"]', str_repr)
                        at_least_one_resolved = True
                    elif f"Literal['{str_repr}']" in typed_signature:
                        typed_signature = typed_signature.replace(f"Literal['{str_repr}']", str_repr)
                        at_least_one_resolved = True
                    # Handle _typeshed.<name> placeholders
                    elif str_repr.startswith("_typeshed.") and f"ForwardRef('{str_repr}')" in typed_signature:
                        typed_signature = typed_signature.replace(f"ForwardRef('{str_repr}')", str_repr)
                        at_least_one_resolved = True
                    elif str_repr.startswith("_typeshed.") and f'ForwardRef("{str_repr}"")' in typed_signature:
                        typed_signature = typed_signature.replace(f'ForwardRef("{str_repr}")', str_repr)
                        at_least_one_resolved = True
                if not at_least_one_resolved:
                    break

        return typed_signature

    # If overloads exist, compute signatures for each overload and include implementation
    try:
        overloads = get_overloads(func) or []
    except Exception:
        overloads = []

    if include_overloads and overloads:
        parts: List[str] = []
        for ov in overloads:
            try:
                parts.append(_compute_single_signature(ov))
            except Exception as e:
                logging.warning(f"Failed to compute overload signature: {e}")
        # Always include the implementation signature last
        try:
            parts.append(_compute_single_signature(func))
        except Exception as e:
            logging.warning(f"Failed to compute implementation signature: {e}")
        # Join with a separator for readability
        return " | ".join(parts)

    # No overloads; just compute the single signature
    return _compute_single_signature(func)
