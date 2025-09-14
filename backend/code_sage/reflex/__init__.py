"""
ReflEx (Reflection and Extraction) Module

This module provides utilities to extract entities and relationships from Python modules and classes, such as:
- Modules
- Classes
- Methods
- Inheritance
- Imports
"""

from .models import Entity, Relationship
from typing import Any, Dict, List, Set, Tuple, Callable, Optional, get_type_hints
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
from pathlib import Path
import json

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


def _function_method_labels(func: Callable, name: str, parent_obj: Optional[Any] = None) -> Tuple[List[str], List[str]]:
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
        print(f"Checking unused imports for {module_name} at {module_file_path}...")

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
    
def safe_get_docstring(obj) -> str:
    """
    Retrieve the docstring of an object or fallback to its representation.

    Args:
        obj: The object to retrieve the docstring for.

    Returns:
        str: The docstring or representation of the object.
    """
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
        print(f"Warning: Could not import or process {module_name}: {e}")
    except Exception as e:
        print(f"Error processing {module_name}: {e}")
    return results

def get_typed_signature(func: Callable) -> inspect.Signature:
    """
    Return an inspect.Signature with annotations resolved like typing.get_type_hints.
    
    Handles forward references, PEP 563 postponed annotations, Optional defaults, etc.

    Args:
        func (Callable): The function to analyze.

    Returns:
        inspect.Signature: A signature object with resolved annotations.
    """
    # First, retrieve evaluated type hints with appropriate namespaces to resolve strings and forward refs.
    globalns: Dict[str, Any] = {}
    localns: Dict[str, Any] = {}
    try:
        mod = inspect.getmodule(func)
        if mod is not None:
            globalns = getattr(mod, "__dict__", {})
        # For functions, __globals__ is also useful
        if hasattr(func, "__globals__") and isinstance(func.__globals__, dict):
            # Prefer function globals but merge with module dict to be safe
            merged = dict(globalns)
            merged.update(func.__globals__)
            globalns = merged
        owner_cls = _owner_class_of_callable(func)
        if owner_cls is not None:
            localns = dict(vars(owner_cls))
    except Exception:
        pass

    # Attempt to enrich globalns/localns with names imported/assigned under `if TYPE_CHECKING` in the owner module
    try:
        mod = inspect.getmodule(func)
        if mod is not None:
            src = safe_get_source(mod)
            # Track visited modules to avoid infinite recursion
            _tc_visited: Set[str] = set()

            def _contains_type_checking(node: ast.AST) -> bool:
                found = False
                for n in ast.walk(node):
                    if isinstance(n, ast.Name) and n.id == "TYPE_CHECKING":
                        return True
                    if isinstance(n, ast.Attribute) and getattr(n, "attr", None) == "TYPE_CHECKING":
                        return True
                return found

            def _resolve_relative(module_name: str | None, level: int, current_module: str) -> str:
                if not level:
                    return module_name or ""
                parts = current_module.split(".")
                # drop last element (module itself)
                if parts:
                    parts = parts[:-1]
                base_len = len(parts)
                up = min(level - 1, base_len)
                base = parts[: base_len - up]
                if module_name:
                    base.append(module_name)
                return ".".join([p for p in base if p])

            def _hydrate_name_from_module_source(target_module: Any, target_name: str) -> Optional[Any]:
                """Evaluate simple assignments to target_name inside TYPE_CHECKING blocks of target_module.
                Returns the value if successfully evaluated, else None.
                """
                try:
                    mod_src = safe_get_source(target_module)
                    if not mod_src or mod_src.startswith("# Representation:"):
                        return None
                    tree = ast.parse(mod_src)
                except Exception:
                    return None

                # Build eval environment
                env: Dict[str, Any] = {}
                try:
                    env.update(getattr(target_module, "__dict__", {}) or {})
                except Exception:
                    pass
                try:
                    import typing as _t
                    env.setdefault("typing", _t)
                    for _n in ("Any", "Callable", "Generator", "Tuple", "List", "Dict", "Set", "Union"):
                        if hasattr(_t, _n):
                            env.setdefault(_n, getattr(_t, _n))
                except Exception:
                    pass
                try:
                    import typing_extensions as _tx
                    env.setdefault("typing_extensions", _tx)
                    for _n in ("Annotated", "Literal", "TypeAlias", "TypeGuard", "Required", "NotRequired"):
                        if hasattr(_tx, _n):
                            env.setdefault(_n, getattr(_tx, _n))
                except Exception:
                    pass

                def walk(node: ast.AST, in_tc: bool = False) -> Optional[Any]:
                    if isinstance(node, ast.If):
                        branch_tc = in_tc or _contains_type_checking(node.test)
                        for b in node.body:
                            res = walk(b, branch_tc)
                            if res is not None:
                                return res
                        for e in node.orelse:
                            res = walk(e, in_tc)
                            if res is not None:
                                return res
                        return None
                    if in_tc and isinstance(node, ast.Assign):
                        # Only handle simple Name targets
                        names = [t.id for t in node.targets if isinstance(t, ast.Name)]
                        if target_name in names:
                            try:
                                code = ast.unparse(node.value)  # type: ignore[attr-defined]
                            except Exception:
                                return None
                            try:
                                val = eval(compile(ast.parse(code, mode="eval"), filename=getattr(target_module, "__file__", "<ast>"), mode="eval"), env, env)  # type: ignore[arg-type]
                                return val
                            except Exception:
                                return None
                    for child in ast.iter_child_nodes(node):
                        res = walk(child, in_tc)
                        if res is not None:
                            return res
                    return None

                try:
                    return walk(tree, in_tc=False)
                except Exception:
                    return None

            def _inject_type_checking_imports(source: str, module_name: str) -> None:
                try:
                    tree = ast.parse(source)
                except Exception:
                    return
                # Walk the AST and collect imports within TYPE_CHECKING blocks
                def walk(node: ast.AST, in_tc: bool = False):
                    # Local eval env seeded from current module plus typing extras
                    def build_env() -> Dict[str, Any]:
                        env: Dict[str, Any] = {}
                        try:
                            env.update(getattr(mod, "__dict__", {}) or {})
                        except Exception:
                            pass
                        # allow names already injected
                        try:
                            env.update(globalns)
                        except Exception:
                            pass
                        try:
                            import typing as _t
                            env.setdefault("typing", _t)
                            # common names
                            for _n in (
                                "Any","Callable","Generator","Tuple","List","Dict","Set","Union","TypeVar",
                                "Optional","Mapping","MutableMapping","Sequence","Iterable","Iterator","Type","ClassVar"
                            ):
                                if hasattr(_t, _n):
                                    env.setdefault(_n, getattr(_t, _n))
                        except Exception:
                            pass
                        try:
                            import typing_extensions as _tx
                            env.setdefault("typing_extensions", _tx)
                            for _n in ("Annotated", "Literal", "TypeAlias", "TypeGuard", "Required", "NotRequired"):
                                if hasattr(_tx, _n):
                                    env.setdefault(_n, getattr(_tx, _n))
                        except Exception:
                            pass
                        return env
                    # If node is an If and condition mentions TYPE_CHECKING, mark branch
                    if isinstance(node, ast.If):
                        branch_tc = in_tc or _contains_type_checking(node.test)
                        for b in node.body:
                            walk(b, branch_tc)
                        # we intentionally do not include orelse when TYPE_CHECKING is True in test
                        for e in node.orelse:
                            walk(e, in_tc)
                        return
                    # Within TYPE_CHECKING: import and from-import
                    if in_tc and isinstance(node, ast.Import):
                        for alias in node.names:
                            mod_name = alias.name
                            try:
                                # ensure submodule is loaded
                                sub = importlib.import_module(mod_name)
                                bind_name = alias.asname
                                if bind_name:
                                    globalns.setdefault(bind_name, sub)
                                else:
                                    # bind top-level package name
                                    top = mod_name.split(".")[0]
                                    top_mod = importlib.import_module(top)
                                    globalns.setdefault(top, top_mod)
                            except Exception:
                                pass
                    if in_tc and isinstance(node, ast.ImportFrom):
                        module = node.module or ""
                        level = getattr(node, "level", 0) or 0
                        full_mod = _resolve_relative(module, level, module_name)
                        try:
                            imported_mod = importlib.import_module(full_mod) if full_mod else importlib.import_module(module_name)
                        except Exception:
                            imported_mod = None
                        for alias in node.names:
                            try:
                                if imported_mod is None:
                                    continue
                                # Try to get attribute directly
                                try:
                                    obj = getattr(imported_mod, alias.name)
                                except AttributeError:
                                    # Recurse into the imported module's TYPE_CHECKING imports once
                                    imported_name = getattr(imported_mod, "__name__", "")
                                    if imported_name and imported_name not in _tc_visited:
                                        _tc_visited.add(imported_name)
                                        _inject_type_checking_imports(safe_get_source(imported_mod), imported_name)
                                    # Try again
                                    if hasattr(imported_mod, alias.name):
                                        obj = getattr(imported_mod, alias.name)
                                    else:
                                        # Last resort: evaluate guarded assignment in that module
                                        val = _hydrate_name_from_module_source(imported_mod, alias.name)
                                        if val is None:
                                            raise AttributeError(alias.name)
                                        obj = val
                                globalns.setdefault(alias.asname or alias.name, obj)
                            except Exception:
                                pass
                    # Within TYPE_CHECKING: handle guarded assignments like `Model = TypeVar(...)`
                    if in_tc and isinstance(node, (ast.Assign, ast.AnnAssign)):
                        try:
                            # Only simple Name targets are supported
                            targets: List[str] = []
                            if isinstance(node, ast.Assign):
                                targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
                                value_node = node.value
                            else:
                                if isinstance(node.target, ast.Name):
                                    targets = [node.target.id]
                                value_node = node.value
                            if targets and value_node is not None:
                                try:
                                    code = ast.unparse(value_node)  # type: ignore[attr-defined]
                                except Exception:
                                    # Log where this failure happens, including the module and target names
                                    # print(f"Warning: Could not unparse AST node for assignment to {targets} in module {getattr(mod, '__name__', '')}")
                                    code = None
                                if code:
                                    env = build_env()
                                    try:
                                        val = eval(compile(ast.parse(code, mode="eval"), filename=getattr(mod, "__file__", "<ast>"), mode="eval"), env, env)  # type: ignore[arg-type]
                                        for tname in targets:
                                            globalns.setdefault(tname, val)
                                    except Exception:
                                        # print(f"Warning: Could not evaluate AST node for assignment to {targets} in module {getattr(mod, '__name__', '')}")
                                        pass
                        except Exception:
                            pass
                    # Recurse
                    for child in ast.iter_child_nodes(node):
                        walk(child, in_tc)

                walk(tree, in_tc=False)

            # Inject guarded imports at module scope
            if src and not src.startswith("# Representation:"):
                _inject_type_checking_imports(src, getattr(mod, "__name__", ""))

            # Also scan owner class for TYPE_CHECKING guarded items
            try:
                if owner_cls is not None:
                    cls_src = safe_get_source(owner_cls)
                    if cls_src and not cls_src.startswith("# Representation:"):
                        _inject_type_checking_imports(cls_src, getattr(mod, "__name__", ""))
            except Exception:
                pass

            # Also scan the function body for TYPE_CHECKING guarded items
            try:
                fn_src = safe_get_source(func)
                if fn_src and not fn_src.startswith("# Representation:"):
                    _inject_type_checking_imports(fn_src, getattr(mod, "__name__", ""))
            except Exception:
                pass

            # Seed common typing/typing_extensions names often used only under TYPE_CHECKING
            try:
                import typing as _typing
                common_names = [
                    "Literal", "Annotated", "TypeAlias", "TypeGuard", "Required", "NotRequired",
                    "Final", "ClassVar", "Self", "ParamSpec", "TypeVar", "Concatenate", "Unpack",
                    "Never", "NoReturn", "Protocol", "TypedDict", "Optional", "Mapping", "MutableMapping",
                    "Sequence", "Iterable", "Iterator", "Type",
                ]
                for _n in common_names:
                    if _n not in globalns and hasattr(_typing, _n):
                        globalns[_n] = getattr(_typing, _n)
            except Exception:
                pass
            try:
                import typing_extensions as _tx
                for _n in ("Literal", "Annotated", "TypeAlias", "TypeGuard", "Required", "NotRequired",
                           "Final", "ClassVar", "Self", "ParamSpec", "Concatenate", "Unpack", "Never"):
                    if _n not in globalns and hasattr(_tx, _n):
                        globalns[_n] = getattr(_tx, _n)
            except Exception:
                pass
    except Exception:
        pass

    # Additionally, hydrate runtime imports and simple assignments used inside the module/function/class bodies
    # (non-TYPE_CHECKING) by traversing all control-flow blocks (if/elif/else, try/except/else/finally, loops).
    def _inject_runtime_imports_from_source(source: str, target_ns: Dict[str, Any], module_name: str) -> None:
        if not source or source.startswith("# Representation:"):
            return
        try:
            tree = ast.parse(source)
        except Exception:
            return

        def resolve_rel(module: Optional[str], level: int) -> str:
            if not level:
                return module or ""
            parts = module_name.split(".")
            if parts:
                parts = parts[:-1]
            up = max(0, level - 1)
            base = parts[: len(parts) - up]
            if module:
                base.append(module)
            return ".".join([p for p in base if p])

        def bind_import(alias: ast.alias) -> None:
            try:
                m = importlib.import_module(alias.name)
                bind = alias.asname or alias.name.split(".")[0]
                # Don't clobber existing values from real module globals
                target_ns.setdefault(bind, m)
            except Exception:
                pass

        def bind_from_import(module_name_full: str, alias: ast.alias) -> None:
            try:
                m = importlib.import_module(module_name_full)
            except Exception:
                return
            try:
                if alias.name == "*":
                    names = getattr(m, "__all__", None)
                    if names is None:
                        names = [n for n in dir(m) if not n.startswith("_")]
                    for n in names:
                        try:
                            target_ns.setdefault(n, getattr(m, n))
                        except Exception:
                            continue
                    return
                obj = getattr(m, alias.name)
                target_ns.setdefault(alias.asname or alias.name, obj)
            except Exception:
                pass

        def eval_assign(value_node: Optional[ast.AST], targets: List[str]) -> None:
            if not targets or value_node is None:
                return
            try:
                code = ast.unparse(value_node)  # type: ignore[attr-defined]
            except Exception:
                code = None
            if not code:
                return
            env = dict(target_ns)
            try:
                val = eval(compile(ast.parse(code, mode="eval"), filename="<ast>", mode="eval"), env, env)  # type: ignore[arg-type]
                for tname in targets:
                    target_ns.setdefault(tname, val)
            except Exception:
                # best-effort only
                pass

        def visit_stmt(node: ast.AST) -> None:
            try:
                if isinstance(node, ast.Import):
                    for a in node.names:
                        bind_import(a)
                    return
                if isinstance(node, ast.ImportFrom):
                    level = getattr(node, "level", 0) or 0
                    full_mod = resolve_rel(node.module or "", level)
                    for a in node.names:
                        bind_from_import(full_mod, a)
                    return
                if isinstance(node, (ast.Assign, ast.AnnAssign)):
                    if isinstance(node, ast.Assign):
                        targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
                        value_node = node.value
                    else:
                        targets = [node.target.id] if isinstance(node.target, ast.Name) else []
                        value_node = node.value
                    eval_assign(value_node, targets)
                    return
                if isinstance(node, ast.If):
                    # Traverse both branches to collect names defined conditionally
                    for b in node.body:
                        visit_stmt(b)
                    for e in node.orelse:
                        visit_stmt(e)
                    return
                if isinstance(node, ast.Try):
                    # Process try first, then except/else/finally without clobbering existing
                    for b in node.body:
                        visit_stmt(b)
                    for h in getattr(node, "handlers", []) or []:
                        for b in getattr(h, "body", []) or []:
                            visit_stmt(b)
                    for e in node.orelse:
                        visit_stmt(e)
                    for f in node.finalbody:
                        visit_stmt(f)
                    return
                if isinstance(node, (ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith)):
                    for b in node.body:
                        visit_stmt(b)
                    for e in node.orelse:
                        visit_stmt(e)
                    return
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):  # nested scopes
                    # We don't need to bind the def itself (module globals already have the runtime object),
                    # but we traverse inside to collect conditional imports/assignments used by annotations.
                    for b in node.body:
                        visit_stmt(b)
                    return
                # Recurse into generic children to catch statements within containers
                for child in ast.iter_child_nodes(node):
                    # Avoid double-walking expressions; we only care about statements
                    if isinstance(child, ast.AST):
                        visit_stmt(child)
            except Exception:
                return

        # Begin traversal from the module/function/class body
        if hasattr(tree, "body") and isinstance(tree.body, list):
            for stmt in tree.body:
                visit_stmt(stmt)

    try:
        mod = inspect.getmodule(func)
        # Module-level: inject runtime imports and simple assignments
        if mod is not None:
            src_mod = safe_get_source(mod)
            _inject_runtime_imports_from_source(src_mod, globalns, getattr(mod, "__name__", ""))

        src_fn = safe_get_source(func)
        _inject_runtime_imports_from_source(src_fn, globalns, getattr(mod, "__name__", ""))
        owner_cls = _owner_class_of_callable(func)
        if owner_cls is not None:
            src_cls = safe_get_source(owner_cls)
            # class-scope imports usually act like module-level for resolution; place into both
            _inject_runtime_imports_from_source(src_cls, globalns, getattr(mod, "__name__", ""))
            # and also into localns so class-only symbols are visible
            _inject_runtime_imports_from_source(src_cls, localns, getattr(mod, "__name__", ""))
    except Exception:
        pass

    # Resolve type hints robustly with layered fallbacks
    hints: Dict[str, Any]
    try:
        # Python 3.13 supports include_extras; pass if available
        try:
            hints = get_type_hints(func, globalns=globalns or None, localns=localns or None, include_extras=True)  # type: ignore[call-arg]
        except TypeError:
            hints = get_type_hints(func, globalns=globalns or None, localns=localns or None)
    except Exception:
        try:
            # Fallback without custom namespaces
            try:
                hints = get_type_hints(func, include_extras=True)  # type: ignore[call-arg]
            except TypeError:
                hints = get_type_hints(func)
        except Exception:
            # Final fallback via typing_extensions if available
            try:
                from typing_extensions import get_type_hints as tx_get_type_hints  # type: ignore
                try:
                    hints = tx_get_type_hints(func, globalns=globalns or None, localns=localns or None)  # type: ignore[call-arg]
                except Exception:
                    hints = {}
            except Exception:
                hints = {}
    
    # Get raw signature
    sig = inspect.signature(func)
    
    # Build new Parameters with resolved annotations
    params: List[inspect.Parameter] = []
    for _pname, param in sig.parameters.items():
        annotation = hints.get(_pname, param.annotation)
        params.append(param.replace(annotation=annotation))
    
    # Determine return annotation
    return_annotation = hints.get('return', sig.return_annotation)
    
    # Construct resolved signature
    return sig.replace(parameters=params, return_annotation=return_annotation)

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
        extra_labels, decorators = _function_method_labels(obj, name, parent_obj=parent_obj)
        labels = ["FUNCTION"] + extra_labels
        if _is_dunder(obj.__name__):
            labels.append("DUNDER")
        if version:
            labels.append(f"version:{version}")
        function_entity = Entity(
            obj_path,
            labels,
            {
                "source": source_code,
                "__name__": obj.__name__,
                "signature": str(get_typed_signature(obj)),
                "docstring": docstring,
                "decorators": decorators,
            }
        )
        entities.append(function_entity)
        if parent_entity:
            relations.append(Relationship(parent_entity, function_entity, "HAS_FUNCTION", {}))

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
        extra_labels, decorators = _function_method_labels(obj, name, parent_obj=parent_obj)
        labels = ["METHOD"] + extra_labels
        if _is_dunder(obj.__name__):
            labels.append("DUNDER")
        if version:
            labels.append(f"version:{version}")
        method_entity = Entity(
            obj_path,
            labels,
            {
                "source": source_code,
                "__name__": obj.__name__,
                "signature": str(get_typed_signature(obj)),
                "docstring": docstring,
                "decorators": decorators,
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
                print(f"Error processing submodule {submodule_path}: {e}")
                print(traceback.format_exc())
                continue
            except Exception as e:
                print(f"Error processing submodule {submodule_path}: {e}")
                print(traceback.format_exc())
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
            print(f"Error processing submodule {submodule_path}: {e}")
            print(traceback.format_exc())
            continue
        except Exception as e:
            print(f"Error processing submodule {submodule_path}: {e}")
            print(traceback.format_exc())
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
    ent_by_name: Dict[str, Entity] = {}
    for e in entities:
        ent_by_name[e.name] = e
    dedup_rel: List[Relationship] = []
    rel_keys: Set[Tuple[str, str, str]] = set()
    for r in relations:
        key = (r.from_entity.name, r.label, r.to_entity.name)
        if key not in rel_keys:
            rel_keys.add(key)
            dedup_rel.append(r)
    entities = list(ent_by_name.values())
    relations = dedup_rel

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

    print(f"Processed {len(entities)} entities and {len(relations)} relations in {module_object.__name__}.")

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
        print(f"Package '{pkg_name}' not found. Attempting to install...")
        try:
            subprocess.run(["pip", "install", pkg_name], check=True)
            print(f"Package '{pkg_name}' installed successfully.")
        except subprocess.CalledProcessError as e:
            print(f"Failed to install package '{pkg_name}': {e}")
            return
    
    top_level_module = get_top_level_module(pkg_name)
    if not top_level_module:
        print(f"Package '{pkg_name}' not found after installation.")
        return
    
    print(f"Processing package '{pkg_name}' with top-level module '{top_level_module}'...")
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