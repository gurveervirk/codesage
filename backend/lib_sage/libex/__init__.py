"""
LibEx (Library Extraction) Module

This module provides utilities to extract entities and relationships from Python modules and classes, such as:
- Modules
- Classes
- Methods
- Inheritance
- Imports
"""

from .models import Entity, Relationship
from typing import Any, Dict, List, Set, Tuple, Callable, Optional, get_type_hints, Literal, get_overloads
from pathlib import Path
import importlib.metadata
import inspect
import importlib
import importlib.resources
import importlib.util
import re
import subprocess
import traceback
import ast
import os
import types
import json
import builtins
import typing
import logging

# --------------------
# Helpers
# --------------------

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


def _visibility_label(name: str) -> str:
    # Private: starts with __ but not dunder (not ending with __)
    if name.startswith("__") and not name.endswith("__"):
        return "PRIVATE"
    # Protected: starts with single underscore
    if name.startswith("_") and not name.startswith("__"):
        return "PROTECTED"
    return "PUBLIC"


def _get_decorators_from_source(src: str) -> List[str]:
    try:
        tree = ast.parse(src)
        fn_node = None
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fn_node = node
                break
        if not fn_node:
            return []
        decos: List[str] = []
        for d in fn_node.decorator_list:
            try:
                decos.append(ast.unparse(d))  # type: ignore[attr-defined]
            except Exception:
                if isinstance(d, ast.Name):
                    decos.append(d.id)
                elif isinstance(d, ast.Attribute):
                    parts = []
                    cur = d
                    while isinstance(cur, ast.Attribute):
                        parts.append(cur.attr)
                        cur = cur.value
                    if isinstance(cur, ast.Name):
                        parts.append(cur.id)
                    decos.append(".".join(reversed(parts)))
                else:
                    decos.append(type(d).__name__)
        return decos
    except Exception:
        return []


def get_function_method_labels(func: Callable, name: str, parent_obj: Optional[Any] = None) -> Tuple[List[str], List[str]]:
    """
    Determine extra labels (ASYNC, GENERATOR, PROPERTY, CLASSMETHOD, STATICMETHOD) and decorators list.
    Also add visibility label.
    Returns (labels, decorators)
    """
    labels: List[str] = []
    # Async / generator
    if inspect.iscoroutinefunction(func) or inspect.isasyncgenfunction(func):
        labels.append("ASYNC")
    if inspect.isgeneratorfunction(func):
        labels.append("GENERATOR")

    # Static analysis of descriptor on the parent class (if any)
    if parent_obj is not None:
        try:
            descriptor = inspect.getattr_static(parent_obj, name)
            if isinstance(descriptor, staticmethod):
                labels.append("STATICMETHOD")
            elif isinstance(descriptor, classmethod):
                labels.append("CLASSMETHOD")
            elif isinstance(descriptor, property):
                labels.append("PROPERTY")
        except Exception:
            pass

    # Decorators from source
    decorators: List[str] = []
    try:
        src = safe_get_source(func)
        decorators = _get_decorators_from_source(src)
        # Also map common decorator names to labels if descriptor wasn't detected
        if "property" in decorators and "PROPERTY" not in labels:
            labels.append("PROPERTY")
        if "staticmethod" in decorators and "STATICMETHOD" not in labels:
            labels.append("STATICMETHOD")
        if "classmethod" in decorators and "CLASSMETHOD" not in labels:
            labels.append("CLASSMETHOD")
    except Exception:
        pass

    # Visibility
    labels.append(_visibility_label(name))
    return labels, decorators

def _is_dunder(name: str) -> bool:
    """Return True if name is a Python dunder like __init__ (starts and ends with __)."""
    return len(name) >= 4 and name.startswith("__") and name.endswith("__")

def _owner_class_of_callable(func: Callable) -> Optional[type]:
    """Try to recover the owning class for a method/function by walking its qualname within the module."""
    try:
        mod = inspect.getmodule(func)
        if mod is None:
            return None
        qual = getattr(func, "__qualname__", "")
        if not qual or "." not in qual:
            return None
        parts = [p for p in qual.split(".") if p and p != "<locals>"]
        # Walk all but the last (function) name
        cur: Any = mod
        for part in parts[:-1]:
            if hasattr(cur, part):
                cur = getattr(cur, part)
            else:
                return None
        return cur if isinstance(cur, type) else None
    except Exception:
        return None

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
        logging.debug(f"Checking unused imports for {module_name} at {module_file_path}...")

        # Run flake8 and capture output
        # If system OS is Windows, use shell=True
        process = None
        if os.name == 'nt':
            process = subprocess.run(
                ["python", "-m", "flake8", "--select", "F401", module_file_path],
                capture_output=True,
                text=True,
                check=True,
                shell=True,
            )
        else:
            # For Unix-like systems, use shell=False
            process = subprocess.run(
                ["python", "-m", "flake8", "--select", "F401", module_file_path],
                capture_output=True,
                text=True,
                check=True,
                shell=False,
            )

        output = process.stdout
        unused_names: List[str] = []

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

        unused_imports: Set[str] = set()
        for full_name in imported_names:
            # if any(name == full_name or full_name.startswith(f"{name}.") for name in unused_names):
            #     unused_imports.add(full_name)
            if any(full_name.endswith(name) for name in unused_names):
                 unused_imports.add(full_name)

        return unused_imports
    except Exception as e:
        logging.error(f"Error getting unused imports for {module_name}: {e}")
        logging.error(traceback.format_exc())
        return set()

def get_fully_qualified_name(cls):
    return f"{cls.__module__}.{cls.__qualname__}"

def safe_get_source(obj) -> str:
    try:
        return inspect.getsource(obj)
    except (OSError, TypeError):
        return f"# Representation:\n{repr(obj)}"
    
def safe_get_docstring(obj) -> str:
    try:
        return inspect.getdoc(obj) or ""
    except (OSError, TypeError):
        return f"# Representation:\n{repr(obj)}"
    
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

module_cache: Dict[str, Any] = {}
def get_namespaces(source: str, module: Any) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """
    Parses the source code to extract import statements and assignments, especially those inside blocks.
    Uses `ast` to safely parse the code without executing it.
    Uses `inspect` to assign values to the imported names and assigned variables.
    Most importantly, this only captures those assignments that define types, not function calls or other similar constructs.
    Handles both absolute and relative imports.
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
                    namespace[as_name] = mapped
                    logging.info(f"Mapped from-import of _typeshed: {alias.name} as {as_name} -> '{mapped}'")
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
                    except Exception:
                        logging.warning(f"Failed to import from module: {abs_mod_name}, name: {alias.name}")
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
        sig = inspect.signature(fn)
        logging.info(f"Inspecting signature for function: {fn.__name__}{sig}")

        typed_params: list[inspect.Parameter] = []

        # Get globals, locals and runtime namespace for type hint resolution
        globalns: Dict[str, Any] = {}
        localns: Dict[str, Any] = {}
        runtime_ns: Dict[str, str] = {}

        try:
            mod = inspect.getmodule(fn)
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
            owner_cls = _owner_class_of_callable(fn)
            if owner_cls is not None:
                localns = dict(vars(owner_cls))
        except Exception as e:
            logging.warning(f"Error occurred while retrieving type hints: {e}")

        # Ensure the root package of the function's module is available in globals (e.g., 'pydantic')
        try:
            mod_name = getattr(inspect.getmodule(fn), "__name__", "")
            root_mod = mod_name.split(".") [0] if mod_name else ""
            if root_mod and root_mod not in globalns:
                try:
                    globalns[root_mod] = importlib.import_module(root_mod)
                except Exception as e:
                    logging.warning(f"Failed to import root module: {root_mod}, error: {e}")
                    pass
        except Exception as e:
            logging.warning(f"Error occurred while ensuring root module is available: {e}")
            pass

        retries = 0
        while retries < 10:
            try:
                type_hints = get_type_hints(fn, globalns=globalns, localns=localns)
                break
            except AttributeError as e:
                # Simplified recovery: do not try to discover/import; just attach a Literal placeholder for the missing attribute
                missing_attr = getattr(e, 'name', None)
                base_obj = getattr(e, 'obj', None)
                if missing_attr is None or base_obj is None:
                    # If we can't identify target object and attribute, propagate the error
                    raise
                try:
                    base_name = getattr(base_obj, '__name__', base_obj.__class__.__name__)
                except Exception:
                    base_name = '<unknown>'
                missing_name = f"{base_name}.{missing_attr}"
                placeholder = typing.Literal[missing_name]
                try:
                    setattr(base_obj, missing_attr, placeholder)
                    globalns[missing_name] = placeholder
                    localns[missing_name] = placeholder
                    runtime_ns[missing_name] = missing_name
                    logging.info(f"Injected placeholder for missing attribute: {base_name}.{missing_attr} -> Literal['{base_name}.{missing_attr}']")
                except Exception:
                    # If we cannot set attribute on the object, re-raise as per requirements
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

def get_top_level_module(package_name: str) -> str:
    """
    Get the top-level module of a package.

    Args:
        package_name (str): The name of the package.

    Returns:
        str: The top-level module of the package.
    """
    mapping = importlib.metadata.packages_distributions()
    top_level_module = ""

    for top_module, distribution in mapping.items():
        if package_name in distribution:
            top_level_module = top_module
            break

    return top_level_module

def process_member(
    name: str,
    obj: Any,
    root_module_path: str,
    parent_entity,
    processed_paths: Set[str],
    other_relations: Dict[str, Set[Tuple]] = None,
    *,
    version: Optional[str] = None,
    parent_obj: Optional[Any] = None,
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
    entities: List[Entity] = []
    relations: List[Relationship] = []

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
            obj, root_module_path, processed_paths, other_relations, version=version
        )
        entities.extend(sub_entities)
        relations.extend(sub_relations)

        relation_type = "HAS_SUBMODULE" if inspect.ismodule(obj) else "HAS_CLASS"
        if entities:
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
        docstring = safe_get_docstring(obj)
        extra_labels, decorators = get_function_method_labels(obj, name, parent_obj=parent_obj)
        # Overload detection
        overloads: List[Callable] = []
        try:
            overloads = get_overloads(obj) or []
        except Exception:
            overloads = []
        labels = ["FUNCTION"] + (extra_labels or [])
        if overloads:
            labels.append("OVERLOADED")
        if _is_dunder(obj.__name__):
            labels.append("DUNDER")
        if version:
            labels.append(f"version:{version}")
        # Collect signature variants
        raw_sig = str(inspect.signature(obj))
        resolved_sig = str(get_typed_signature(obj, include_overloads=False))
        function_entity = Entity(
            obj_path,
            labels,
            {
                "source": source_code,
                "__name__": obj.__name__,
                "signature": raw_sig,
                "resolved_signature": resolved_sig,
                "docstring": docstring,
                "decorators": decorators,
            }
        )
        entities.append(function_entity)
        if parent_entity:
            relations.append(Relationship(parent_entity, function_entity, "HAS_FUNCTION", {}))
        # Create individual overload entities
        if overloads:
            for idx, ov in enumerate(overloads, start=1):
                try:
                    ov_src = safe_get_source(ov)
                except Exception:
                    ov_src = ""
                ov_doc = safe_get_docstring(ov)
                ov_extra_labels, ov_decorators = get_function_method_labels(ov, name, parent_obj=parent_obj)
                ov_labels = ["FUNCTION", "OVERLOAD"] + (ov_extra_labels or [])
                if _is_dunder(obj.__name__):
                    ov_labels.append("DUNDER")
                if version:
                    ov_labels.append(f"version:{version}")
                ov_sig_raw = str(inspect.signature(ov)) if hasattr(ov, "__call__") or inspect.isfunction(ov) else "<unavailable>"
                try:
                    ov_sig_res = str(get_typed_signature(ov, include_overloads=False))
                except Exception:
                    ov_sig_res = ov_sig_raw
                ov_entity = Entity(
                    obj_path,
                    ov_labels,
                    {
                        "source": ov_src,
                        "__name__": getattr(ov, "__name__", name),
                        "signature": ov_sig_raw,
                        "resolved_signature": ov_sig_res,
                        "docstring": ov_doc,
                        "decorators": ov_decorators,
                    },
                )
                entities.append(ov_entity)
                if parent_entity:
                    relations.append(Relationship(parent_entity, ov_entity, "HAS_FUNCTION", {}))
                relations.append(Relationship(function_entity, ov_entity, "HAS_OVERLOAD", {}))

    elif parent_entity.label == "CLASS" and (inspect.ismethod(obj) or inspect.isfunction(obj)):
        obj_path = get_fully_qualified_name(obj)

        if not obj_path.startswith(root_module_path + ".") or not obj_path.startswith(parent_entity.name + "."):
            return [], []

        if obj_path in processed_paths:
            return [], []
        else:
            processed_paths.add(obj_path)

        source_code = safe_get_source(obj)
        docstring = safe_get_docstring(obj)
        extra_labels, decorators = get_function_method_labels(obj, name, parent_obj=parent_obj)
        # Overload detection
        overloads: List[Callable] = []
        try:
            overloads = get_overloads(obj) or []
        except Exception:
            overloads = []
        labels = ["METHOD"] + (extra_labels or [])
        if overloads:
            labels.append("OVERLOADED")
        if _is_dunder(obj.__name__):
            labels.append("DUNDER")
        if version:
            labels.append(f"version:{version}")
        # Collect signature variants
        raw_sig = str(inspect.signature(obj))
        resolved_sig = str(get_typed_signature(obj, include_overloads=False))
        method_entity = Entity(
            obj_path,
            labels,
            {
                "source": source_code,
                "__name__": obj.__name__,
                "signature": raw_sig,
                "resolved_signature": resolved_sig,
                "docstring": docstring,
                "decorators": decorators,
            }
        )
        entities.append(method_entity)
        if parent_entity:
            relations.append(Relationship(parent_entity, method_entity, "HAS_METHOD", {}))
        # Create individual overload entities for methods
        if overloads:
            for idx, ov in enumerate(overloads, start=1):
                try:
                    ov_src = safe_get_source(ov)
                except Exception:
                    ov_src = ""
                ov_doc = safe_get_docstring(ov)
                ov_extra_labels, ov_decorators = get_function_method_labels(ov, name, parent_obj=parent_obj)
                ov_labels = ["METHOD", "OVERLOAD"] + (ov_extra_labels or [])
                if _is_dunder(obj.__name__):
                    ov_labels.append("DUNDER")
                if version:
                    ov_labels.append(f"version:{version}")
                ov_sig_raw = str(inspect.signature(ov)) if hasattr(ov, "__call__") or inspect.isfunction(ov) else "<unavailable>"
                try:
                    ov_sig_res = str(get_typed_signature(ov, include_overloads=False))
                except Exception:
                    ov_sig_res = ov_sig_raw
                ov_entity = Entity(
                    obj_path,
                    ov_labels,
                    {
                        "source": ov_src,
                        "__name__": getattr(ov, "__name__", name),
                        "signature": ov_sig_raw,
                        "resolved_signature": ov_sig_res,
                        "docstring": ov_doc,
                        "decorators": ov_decorators,
                    },
                )
                entities.append(ov_entity)
                if parent_entity:
                    relations.append(Relationship(parent_entity, ov_entity, "HAS_METHOD", {}))
                relations.append(Relationship(method_entity, ov_entity, "HAS_OVERLOAD", {}))

    return entities, relations

def traverse_recursive(
    obj: Any,
    root_module_path: str,
    processed_paths: Set[str],
    other_relations: Dict[str, Set[Tuple]] = None,
    *,
    version: Optional[str] = None,
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
    entities: List[Entity] = []
    relations: List[Relationship] = []
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
    docstring = safe_get_docstring(obj)
    properties = {
        "source": source,
        "__name__": obj.__name__,
        "docstring": docstring
    }

    if inspect.ismodule(obj):
        properties["import_statements"] = get_import_statements(source)
        properties["import_as_aliases"] = get_import_as_aliases(source, obj_path)

    labels = [entity_type]
    if version:
        labels.append(f"version:{version}")
    if entity_type == "CLASS":
        labels.append(_visibility_label(obj.__name__))
        if _is_dunder(obj.__name__):
            labels.append("DUNDER")

    entity = Entity(obj_path, labels, properties)
    entities.append(entity)

    if inspect.isclass(obj):
        for base in obj.__bases__:
            if base.__name__ not in ["object", "type"]:
                try:
                    base_path = f"{base.__module__}.{base.__qualname__}"
                    if base_path != obj_path:
                        other_relations["INHERITS"].add((obj_path, base_path))
                except Exception:
                    pass

    # Get all sub-modules using `find_submodules_importlib_resources` and process them, if the object is a module
    if inspect.ismodule(obj):
        submodules: set = find_submodules_importlib_resources(obj_path)
        for submodule_path in submodules:
            try:
                submodule_name = submodule_path.split(".")[-1]
                sub_entities, sub_relations = process_member(
                    submodule_name,
                    importlib.import_module(submodule_path),
                    root_module_path,
                    entity,
                    processed_paths,
                    other_relations,
                    version=version,
                    parent_obj=obj,
                )
                entities.extend(sub_entities)
                relations.extend(sub_relations)
            except ModuleNotFoundError as e:
                # If the missing module is external to the root, skip quietly
                missing = getattr(e, 'name', '') or ''
                if missing and not missing.startswith(root_module_path):
                    continue
                logging.error(f"Error processing submodule {submodule_path}: {e}")
                logging.error(traceback.format_exc())
                continue
            except Exception as e:
                logging.error(f"Error processing submodule {submodule_path}: {e}")
                logging.error(traceback.format_exc())
                continue

    # Process sub-classes
    for name, member in inspect.getmembers(obj, inspect.isclass):
        sub_entities, sub_relations = process_member(
            name, member, root_module_path, entity, processed_paths, other_relations, version=version, parent_obj=obj
        )
        entities.extend(sub_entities)
        relations.extend(sub_relations)

    # Process functions
    for name, member in inspect.getmembers(obj, inspect.isfunction):
        sub_entities, sub_relations = process_member(
            name, member, root_module_path, entity, processed_paths, other_relations, version=version, parent_obj=obj
        )
        entities.extend(sub_entities)
        relations.extend(sub_relations)

    # Process methods
    for name, member in inspect.getmembers(obj, inspect.ismethod):
        sub_entities, sub_relations = process_member(
            name, member, root_module_path, entity, processed_paths, other_relations, version=version, parent_obj=obj
        )
        entities.extend(sub_entities)
        relations.extend(sub_relations)

    return entities, relations

def process_module(module_name: str, version: Optional[str] = None):
    """
    Process a module or object recursively.

    Args:
        module_name (str): Module name or object.

    Returns:
        Tuple[List[Entity], List[Relation], Dict]: List of entities, list of relations, and other relations.
    """
    name_only, parsed_version = _parse_name_and_version(module_name, version)
    version = parsed_version

    entities: List[Entity] = []
    relations: List[Relationship] = []
    processed_paths: Set[str] = set()
    other_relations: Dict[str, Set[Tuple]] = {"INHERITS": set(), "IMPORTS": set(), "EXPOSES": set()}

    module_object = importlib.import_module(name_only)

    source = safe_get_source(module_object)
    docstring = safe_get_docstring(module_object)
    all_import_statements = get_import_statements(source)
    import_as_aliases = get_import_as_aliases(source, module_object.__name__)
    properties = {
        "source": source,
        "docstring": docstring,
        "__name__": module_object.__name__,
        "import_statements": all_import_statements,
        "import_as_aliases": import_as_aliases
    }

    labels = ["ROOT_MODULE"]
    if version:
        labels.append(f"version:{version}")
    root_entity = Entity(module_object.__name__, labels, properties)
    entities.append(root_entity)

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

    # Convert IMPORTS to EXPOSES for unused imports
    imported_relations = other_relations["IMPORTS"]
    updated_imported_relations: Set[Tuple[str, str]] = set()
    module_to_imports: Dict[str, Set[str]] = {}

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

    cleaned_exposed_relations: Set[Tuple[str, str]] = set()
    cleaned_imports_relations: Set[Tuple[str, str]] = set()

    # Clean up IMPORTS relations
    for from_entity, to_entity in other_relations["IMPORTS"]:
        to_entity_ancestor_path = ".".join(to_entity.split(".")[:-1])
        if to_entity_ancestor_path == from_entity:
            continue
        elif to_entity.startswith(module_name):
            other_relations["EXPOSES"].add((from_entity, to_entity))
        else:
            cleaned_imports_relations.add((from_entity, to_entity))

    # Clean up EXPOSED relations
    for from_entity, to_entity in other_relations["EXPOSES"]:
        if not to_entity.startswith(from_entity):
            continue
        cleaned_exposed_relations.add((from_entity, to_entity))

    # Deduplicate entities and relations (Entity isn't hashable; use name)
    # ent_by_name: Dict[str, Entity] = {}
    # for e in entities:
    #     ent_by_name[e.name] = e
    # dedup_rel: List[Relationship] = []
    # rel_keys: Set[Tuple[str, str, str]] = set()
    # for r in relations:
    #     key = (r.from_entity.name, r.label, r.to_entity.name)
    #     if key not in rel_keys:
    #         rel_keys.add(key)
    #         dedup_rel.append(r)
    # entities = list(ent_by_name.values())
    # relations = dedup_rel

    # Clean up Alias Imports
    for entity in entities:
        if entity.label not in ("ROOT_MODULE", "MODULE"):
            continue

        cleaned_import_aliases: List[Tuple[str, str]] = []
        for key, value in entity.properties.get("import_as_aliases", []):
            if (entity.name, key) in other_relations["EXPOSES"] or (entity.name, key) in other_relations["IMPORTS"]:
                cleaned_import_aliases.append((key, value))
        if cleaned_import_aliases:
            entity.properties["import_as_aliases"] = cleaned_import_aliases

    other_relations["EXPOSES"] = list(cleaned_exposed_relations)
    other_relations["IMPORTS"] = list(cleaned_imports_relations)
    other_relations["INHERITS"] = list(other_relations["INHERITS"])

    logging.info(f"Processed {len(entities)} entities and {len(relations)} relations in {module_object.__name__}.")

    return entities, relations, other_relations

def process_package(package_name: str, version: Optional[str] = None):
    """
    Process the top-level module of a package. If the package is not available, it will try installing it using pip.

    Args:
        package_name (str): The name of the package.
    """
    pkg_name, parsed_version = _parse_name_and_version(package_name, version)
    version = parsed_version
    top_level_module = get_top_level_module(pkg_name)

    if not top_level_module:
        logging.info(f"Package '{pkg_name}' not found. Attempting to install...")
        try:
            subprocess.run(["pip", "install", pkg_name], check=True)
            logging.info(f"Package '{pkg_name}' installed successfully.")
        except subprocess.CalledProcessError as e:
            logging.error(f"Failed to install package '{pkg_name}': {e}")
            return
    
    top_level_module = get_top_level_module(pkg_name)
    if not top_level_module:
        logging.error(f"Package '{pkg_name}' not found after installation.")
        return
    
    logging.info(f"Processing package '{pkg_name}' with top-level module '{top_level_module}'...")
    return process_module(top_level_module, version=version)

def visualize_to_html(entities: List[Entity], relations: List[Relationship], out_file: Optional[str] = None) -> str:
    """
    Generate a simple searchable HTML visualization of entities and relations.
    Returns the HTML string and optionally writes it to out_file.
    """
    def esc(s: Any) -> str:
        try:
            return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        except Exception:
            return str(s)

    # Serialize data for fast client-side rendering & search
    ents_data = []
    for e in entities:
        ents_data.append({
            "name": e.name,
            "labels": ", ".join(e.labels),
            "dname": e.properties.get("__name__", ""),
            "sig": e.properties.get("signature", ""),
            "found": ", ".join(e.properties.get("found_types", [])),
        })
    rels_data = []
    for r in relations:
        rels_data.append({
            "from": r.from_entity.name,
            "label": r.label,
            "to": r.to_entity.name,
        })

    html = """
<!DOCTYPE html>
<html lang=\"en\">
<head>
    <meta charset=\"UTF-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />
    <title>CodeSage Reflex Visualization</title>
    <style>
        :root {{ --row-h: 28px; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, 'Helvetica Neue', sans-serif; margin: 16px; }}
        .section {{ margin-bottom: 40px; }}
        .muted {{ color: #6b7280; font-size: 12px; }}
        .controls {{ display: flex; gap: 8px; align-items: center; margin: 8px 0 12px; flex-wrap: wrap; }}
        .search {{ flex: 1; min-width: 260px; }}
        input[type="search"] {{ width: 100%; padding: 8px; border: 1px solid #d1d5db; border-radius: 6px; }}
        .count {{ color: #6b7280; font-size: 12px; }}
    .grid {{ display: grid; grid-template-columns: var(--cols); border: 1px solid #e5e7eb; border-radius: 6px; overflow: hidden; }}
    .header {{ display: contents; }}
    .cell.h {{ background: #f9fafb; font-weight: 600; }}
    .cell {{ padding: 6px 8px; border-bottom: 1px solid #eee; font-size: 13px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
    .list {{ position: relative; height: 420px; overflow: auto; border: 1px solid #e5e7eb; border-radius: 6px; border-top: none; }}
    .canvas {{ position: relative; height: 0px; }}
    .r {{ position: absolute; left: 0; right: 0; display: grid; grid-template-columns: var(--cols); }}
        .mono {{ font-family: ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,'Liberation Mono','Courier New',monospace; }}
    </style>
    <script>
        const ents = __ENTS__;
        const rels = __RELS__;

        // Augment items with search text
        for (const e of ents) {{ e._q = (e.name+" "+e.labels+" "+e.dname+" "+e.sig+" "+e.found).toLowerCase(); }}
        for (const r of rels) {{ r._q = (r.from+" "+r.label+" "+r.to).toLowerCase(); }}

        class VirtualList {
            constructor(listEl, items, renderRow, columnsDef) {
                this.viewport = listEl; // scrollable element
                this.canvas = document.createElement('div');
                this.canvas.className = 'canvas';
                this.viewport.innerHTML = '';
                this.viewport.appendChild(this.canvas);
                this.items = items;
                this.filtered = items;
                this.renderRow = renderRow;
                this.rowH = parseInt(getComputedStyle(document.documentElement).getPropertyValue('--row-h')) || 28;
                this.columnsDef = columnsDef;
                this.countEl = null;
                this.viewport.addEventListener('scroll', () => this._render());
                this._render(true);
            }
            setItems(items) {
                this.items = items;
                this.filtered = items;
                this._render(true);
            }
            filter(query) {
                const q = query.trim().toLowerCase();
                if (!q) this.filtered = this.items; else this.filtered = this.items.filter(it => it._q.includes(q));
                this._render(true);
            }
            _render(reset=false) {
                const H = this.viewport.clientHeight;
                const total = this.filtered.length;
                const vh = this.rowH;
                const buffer = 8;
                const scrollTop = this.viewport.scrollTop;
                const start = Math.max(Math.floor(scrollTop / vh) - buffer, 0);
                const visible = Math.ceil(H / vh) + 2*buffer;
                const end = Math.min(start + visible, total);

                this.canvas.style.height = (total * vh) + 'px';

                // Clear existing rows
                this.canvas.innerHTML = '';

                const frag = document.createDocumentFragment();
                for (let i = start; i < end; i++) {
                    const row = document.createElement('div');
                    row.className = 'r mono';
                    row.style.top = (i * vh) + 'px';
                    row.style.height = vh + 'px';
                    row.style.setProperty('--cols', this.columnsDef);
                    const cells = this.renderRow(this.filtered[i]);
                    for (const c of cells) row.appendChild(c);
                    frag.appendChild(row);
                }
                this.canvas.appendChild(frag);
                if (this.countEl) this.countEl.textContent = (total.toLocaleString()) + ' rows';
                if (reset) this.viewport.scrollTop = 0;
            }
        }

        function mkCell(text, cls='cell') {{ const d=document.createElement('div'); d.className=cls; d.textContent=text; return d; }}

        function init() {{
            // Entities
            const entCols = '2fr 1fr 1fr 2fr 1fr';
            const entContainer = document.getElementById('entities');
            const entList = new VirtualList(entContainer, ents, (e) => [
                mkCell(e.name), mkCell(e.labels), mkCell(e.dname), mkCell(e.sig), mkCell(e.found)
            ], entCols);
            entList.countEl = document.getElementById('entCount');
            const entInput = document.getElementById('searchEnt');
            entInput.addEventListener('input', () => entList.filter(entInput.value));

            // Relationships
            const relCols = '2fr 1fr 2fr';
            const relContainer = document.getElementById('relations');
            const relList = new VirtualList(relContainer, rels, (r) => [
                mkCell(r.from), mkCell(r.label), mkCell(r.to)
            ], relCols);
            relList.countEl = document.getElementById('relCount');
            const relInput = document.getElementById('searchRel');
            relInput.addEventListener('input', () => relList.filter(relInput.value));
        }
        window.addEventListener('DOMContentLoaded', init);
    </script>
    </head>
    <body>
        <h1>CodeSage Reflex Visualization</h1>
        <p class=\"muted\">Fast client-side search with virtualized lists. Use the search boxes to filter.</p>
        <div class=\"section\">
            <h2>Entities <span id=\"entCount\" class=\"count\"></span></h2>
            <div class=\"controls\">
                <div class=\"search\"><input id=\"searchEnt\" type=\"search\" placeholder=\"Search entities...\" /></div>
            </div>
            <div class=\"grid mono\" style=\"--cols: 2fr 1fr 1fr 2fr 1fr\"> 
                <div class=\"header\">
                    <div class=\"cell h\">Name</div><div class=\"cell h\">Labels</div><div class=\"cell h\">__name__</div><div class=\"cell h\">Signature</div><div class=\"cell h\">Found Types</div>
                </div>
            </div>
            <div id=\"entities\" class=\"list\"></div>
        </div>
        <div class=\"section\">
            <h2>Relationships <span id=\"relCount\" class=\"count\"></span></h2>
            <div class=\"controls\">
                <div class=\"search\"><input id=\"searchRel\" type=\"search\" placeholder=\"Search relationships...\" /></div>
            </div>
            <div class=\"grid mono\" style=\"--cols: 2fr 1fr 2fr\"> 
                <div class=\"header\">
                    <div class=\"cell h\">From</div><div class=\"cell h\">Label</div><div class=\"cell h\">To</div>
                </div>
            </div>
            <div id=\"relations\" class=\"list\"></div>
        </div>
    </body>
    </html>
"""
    # Inject JSON safely
    html = html.replace("__ENTS__", json.dumps(ents_data)).replace("__RELS__", json.dumps(rels_data))
    if out_file:
        Path(out_file).write_text(html, encoding="utf-8")
    return html