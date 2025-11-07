"""
COMExtractor (Code Object Model Extractor) Module

This module provides utilities to extract entities and relationships from Python modules and classes, such as:
- Modules
- Classes
- Methods
- Inheritance
- Imports
"""

from .models import Entity, Relationship, ExternalEntityRef
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


def _get_entity_version(entity_path: str) -> Optional[str]:
    """
    Try to determine the version of an external entity by looking at its module's package.
    
    Args:
        entity_path: Fully qualified path like 'numpy.ndarray' or 'pandas.DataFrame'
    
    Returns:
        Version string if found, None otherwise
    """
    try:
        # Extract the root package name (first component)
        root_package = entity_path.split('.')[0]
        
        # Try to get version from importlib.metadata
        try:
            version = importlib.metadata.version(root_package)
            return version
        except importlib.metadata.PackageNotFoundError:
            pass
        
        # Try to get version from __version__ attribute if module is loaded
        try:
            module = importlib.import_module(root_package)
            if hasattr(module, '__version__'):
                return str(module.__version__)
        except Exception:
            pass
        
        return None
    except Exception as e:
        logging.debug(f"Could not determine version for {entity_path}: {e}")
        return None


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
    Also checks if imports are only used in __all__ (re-exports) and treats them as unused.

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
            return set()

        output = process.stdout
        unused_names: List[str] = []

        # Parse the output for unused import errors (F401), extracting the simple names
        for line in output.splitlines():
            match = re.search(r":\d+:(\d+): F401 '(.*)' imported but unused", line)
            if match:
                unused_names.append(match.group(2))
        
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
                            unused_names.append(all_name)
                            logging.debug(f"Import '{all_name}' only used in __all__, treating as exposed")
        
        except Exception as e:
            logging.debug(f"Could not parse __all__ for {module_name}: {e}")

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

        if module_name == "pytest":
            logging.info("Found these:", unused_imports)

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

def create_mock_typeshed_module():
    """Create a mock _typeshed module that can be used in the namespace."""
    import types
    mock_module = types.ModuleType("_typeshed")
    mock_module.__file__ = "<_typeshed>"
    return mock_module

module_cache: Dict[str, Any] = {}
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
                type_hints = get_type_hints(target_for_hints, globalns=globalns, localns=localns)
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
    mapping = importlib.metadata.packages_distributions()

    for top_module, distributions in mapping.items():
        # Check if package_name is in any of the distributions for this top-level module
        if package_name in distributions:
            if top_module not in top_level_modules:
                top_level_modules.append(top_module)

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

def process_member(
    name: str,
    obj: Any,
    root_module_path: str,
    parent_entity: Entity,
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
                # Detect version for external imports
                import_version = _get_entity_version(obj_path)
                import_ref = ExternalEntityRef(name=obj_path, version=import_version)
                other_relations["IMPORTS"].add((parent_entity.content_hash, import_ref))
            return [], []

        if obj_path in processed_paths:
            if parent_entity and parent_entity.label in {"ROOT_MODULE", "MODULE"}:
                # Internal import - use content_hash for from_entity
                import_version = version  # Use module version for internal imports
                import_ref = ExternalEntityRef(name=obj_path, version=import_version)
                other_relations["IMPORTS"].add((parent_entity.content_hash, import_ref))
            return [], []

        if not obj_path.startswith(parent_entity.name + "."):
            if parent_entity and parent_entity.label in {"ROOT_MODULE", "MODULE"}:
                # Detect version for external imports
                import_version = _get_entity_version(obj_path)
                import_ref = ExternalEntityRef(name=obj_path, version=import_version)
                other_relations["IMPORTS"].add((parent_entity.content_hash, import_ref))
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
                import_version = _get_entity_version(obj_path)
                import_ref = ExternalEntityRef(name=obj_path, version=import_version)
                other_relations["IMPORTS"].add((parent_entity.content_hash, import_ref))
            return [], []

        if obj_path in processed_paths:
            if parent_entity and parent_entity.label in {"ROOT_MODULE", "MODULE"}:
                import_version = version
                import_ref = ExternalEntityRef(name=obj_path, version=import_version)
                other_relations["IMPORTS"].add((parent_entity.content_hash, import_ref))
            return [], []

        elif not obj_path.startswith(parent_entity.name + "."):
            if parent_entity and parent_entity.label in {"ROOT_MODULE", "MODULE"}:
                import_version = _get_entity_version(obj_path)
                import_ref = ExternalEntityRef(name=obj_path, version=import_version)
                other_relations["IMPORTS"].add((parent_entity.content_hash, import_ref))
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
                        # Try to detect version for external entities
                        base_version = _get_entity_version(base_path) if not base_path.startswith(root_module_path + ".") else version
                        # Create ExternalEntityRef for the base class
                        base_ref = ExternalEntityRef(name=base_path, version=base_version)
                        # Store as (child_name, ExternalEntityRef)
                        other_relations["INHERITS"].add((obj_path, base_ref))
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

    # Process ROOT_MODULE's direct imports
    # Extract imports from the root module's source using AST
    try:
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    try:
                        imported_module = importlib.import_module(alias.name)
                        imported_path = imported_module.__name__
                        # Only track external imports (not within the same root module)
                        if not imported_path.startswith(module_object.__name__ + "."):
                            import_version = _get_entity_version(imported_path)
                            import_ref = ExternalEntityRef(name=imported_path, version=import_version)
                            other_relations["IMPORTS"].add((root_entity.content_hash, import_ref))
                    except Exception as e:
                        logging.debug(f"Could not process import {alias.name}: {e}")
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    try:
                        # Resolve the module being imported from
                        from_module = node.module
                        imported_module = importlib.import_module(from_module)
                        
                        # Process each imported name
                        for alias in node.names:
                            try:
                                imported_obj = getattr(imported_module, alias.name)
                                if inspect.ismodule(imported_obj):
                                    imported_path = imported_obj.__name__
                                elif inspect.isclass(imported_obj) or inspect.isfunction(imported_obj):
                                    imported_path = get_fully_qualified_name(imported_obj)
                                else:
                                    # For other objects, construct the path
                                    imported_path = f"{from_module}.{alias.name}"
                                
                                # Only track external imports
                                if not imported_path.startswith(module_object.__name__ + "."):
                                    import_version = _get_entity_version(imported_path)
                                    import_ref = ExternalEntityRef(name=imported_path, version=import_version)
                                    other_relations["IMPORTS"].add((root_entity.content_hash, import_ref))
                            except AttributeError:
                                # Attribute doesn't exist, still track it
                                imported_path = f"{from_module}.{alias.name}"
                                if not imported_path.startswith(module_object.__name__ + "."):
                                    import_version = _get_entity_version(imported_path)
                                    import_ref = ExternalEntityRef(name=imported_path, version=import_version)
                                    other_relations["IMPORTS"].add((root_entity.content_hash, import_ref))
                            except Exception as e:
                                logging.debug(f"Could not process import {alias.name} from {from_module}: {e}")
                    except Exception as e:
                        logging.debug(f"Could not process import from {node.module}: {e}")
    except Exception as e:
        logging.warning(f"Error parsing imports from root module source: {e}")

    logging.warning('Extracted IMPORTS for ' + module_name + ' as follows: ' + str(other_relations['IMPORTS']))

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
    
    # Convert IMPORTS to EXPOSES for unused imports
    # Now working with (content_hash, ExternalEntityRef) tuples
    imported_relations = other_relations["IMPORTS"]
    updated_imported_relations: Set[Tuple[str, ExternalEntityRef]] = set()
    module_hash_to_imports: Dict[str, Set[str]] = {}

    for from_hash, to_ref in imported_relations:
        # Get the entity name for unused import detection
        from_entity = hash_to_entity.get(from_hash)
        if not from_entity:
            continue
            
        full_module_path = from_entity.name

        if full_module_path not in module_hash_to_imports:
            module_hash_to_imports[full_module_path] = set()

        module_hash_to_imports[full_module_path].add(to_ref.name)

    for module_name_key, imports in module_hash_to_imports.items():
        unused_imports = get_unused_imports(module_name_key, imports)
        used_imports = set(imports) - set(unused_imports)

        # Find the entity for this module
        module_entity = next((e for e in entities if e.name == module_name_key), None)
        if not module_entity:
            continue
            
        for unused_import in unused_imports:
            # Find the original ExternalEntityRef for this import
            for from_hash, to_ref in imported_relations:
                if from_hash == module_entity.content_hash and to_ref.name == unused_import:
                    other_relations["EXPOSES"].add((from_hash, to_ref))
                    break

        for used_import in used_imports:
            # Find the original ExternalEntityRef for this import
            for from_hash, to_ref in imported_relations:
                if from_hash == module_entity.content_hash and to_ref.name == used_import:
                    updated_imported_relations.add((from_hash, to_ref))
                    break

    other_relations["IMPORTS"] = updated_imported_relations

    cleaned_exposed_relations: Set[Tuple[str, ExternalEntityRef]] = set()
    cleaned_imports_relations: Set[Tuple[str, ExternalEntityRef]] = set()

    # Clean up IMPORTS relations
    for from_hash, to_ref in other_relations["IMPORTS"]:
        from_entity = hash_to_entity.get(from_hash)
        if not from_entity:
            continue
            
        to_entity_ancestor_path = ".".join(to_ref.name.split(".")[:-1])
        if to_entity_ancestor_path == from_entity.name:
            continue
        elif to_ref.name.startswith(module_object.__name__):
            other_relations["EXPOSES"].add((from_hash, to_ref))
        else:
            cleaned_imports_relations.add((from_hash, to_ref))

    # Clean up EXPOSED relations
    for from_hash, to_ref in other_relations["EXPOSES"]:
        from_entity = hash_to_entity.get(from_hash)
        if not from_entity:
            continue
        
        # Check if this is a valid EXPOSES relationship:
        # 1. Normal case: to_ref.name starts with from_entity.name (e.g., pytest.Config exposed by pytest)
        # 2. _<package> pattern: from_entity is from _<package> and to_ref is from the main package
        #    (e.g., _pytest.config.Config exposed by pytest when imported in pytest/__init__.py)
        
        is_valid_expose = False
        
        # Case 1: Normal internal expose
        if to_ref.name.startswith(from_entity.name):
            is_valid_expose = True
        
        # Case 2: _<package> pattern - check if from_entity is in a _<package> module
        # and to_ref is being exposed to the main <package>
        else:
            # Extract root module names
            from_root = from_entity.name.split(".")[0]
            to_root = to_ref.name.split(".")[0]
            
            # Check if from_root is _<something> and to_root is <something>
            if from_root.startswith("_") and to_root == from_root[1:]:
                is_valid_expose = True
                logging.debug(f"Found _<package> pattern expose: {from_entity.name} exposes {to_ref.name}")
            # Also check reverse: from_root is <something> and to_root is _<something>
            elif to_root.startswith("_") and from_root == to_root[1:]:
                is_valid_expose = True
                logging.debug(f"Found <package> to _<package> pattern expose: {from_entity.name} exposes {to_ref.name}")
        
        if is_valid_expose:
            cleaned_exposed_relations.add((from_hash, to_ref))

    # Clean up Alias Imports
    for entity in entities:
        if entity.label not in ("ROOT_MODULE", "MODULE"):
            continue

        cleaned_import_aliases: List[Tuple[str, str]] = []
        for key, value in entity.properties.get("import_as_aliases", []):
            # Check if this alias is in EXPOSES or IMPORTS using content_hash
            found = False
            for from_hash, to_ref in other_relations["EXPOSES"]:
                if from_hash == entity.content_hash and to_ref.name == key:
                    found = True
                    break
            if not found:
                for from_hash, to_ref in other_relations["IMPORTS"]:
                    if from_hash == entity.content_hash and to_ref.name == key:
                        found = True
                        break
            if found:
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
    Process all top-level modules associated with a package name.
    
    This function finds all packages/distributions that contain the given package_name,
    processes each of their top-level modules, and combines the results.
    Each top-level module is treated as a ROOT_MODULE.

    Args:
        package_name (str): The name of the package.
        version (Optional[str]): Version of the package.
        
    Returns:
        Tuple[List[Entity], List[Relationship], Dict]: Combined entities, relations, and other relations
            from all top-level modules associated with the package.
    """
    pkg_name, parsed_version = _parse_name_and_version(package_name, version)
    version = parsed_version
    top_level_modules = get_top_level_modules_for_package(pkg_name)

    if not top_level_modules:
        logging.info(f"Package '{pkg_name}' not found. Attempting to install...")
        try:
            subprocess.run(["pip", "install", pkg_name], check=True)
            logging.info(f"Package '{pkg_name}' installed successfully.")
        except subprocess.CalledProcessError as e:
            logging.error(f"Failed to install package '{pkg_name}': {e}")
            return [], [], {"INHERITS": [], "IMPORTS": [], "EXPOSES": []}
    
    top_level_modules = get_top_level_modules_for_package(pkg_name)
    if not top_level_modules:
        logging.error(f"Package '{pkg_name}' not found after installation.")
        return [], [], {"INHERITS": [], "IMPORTS": [], "EXPOSES": []}
    
    # Process all top-level modules and combine results
    all_entities: List[Entity] = []
    all_relations: List[Relationship] = []
    combined_other_relations: Dict[str, List] = {"INHERITS": [], "IMPORTS": [], "EXPOSES": []}
    
    logging.info(f"Processing package '{pkg_name}' with {len(top_level_modules)} top-level module(s): {top_level_modules}")
    
    for top_level_module in top_level_modules:
        logging.info(f"Processing top-level module '{top_level_module}' for package '{pkg_name}'...")
        try:
            entities, relations, other_relations = process_module(top_level_module, version=version)
            
            all_entities.extend(entities)
            all_relations.extend(relations)
            
            # Combine other_relations
            for rel_type in ["INHERITS", "IMPORTS", "EXPOSES"]:
                if rel_type in other_relations:
                    combined_other_relations[rel_type].extend(other_relations[rel_type])
                    
            logging.info(f"Successfully processed top-level module '{top_level_module}': "
                        f"{len(entities)} entities, {len(relations)} relations")
        except Exception as e:
            logging.error(f"Error processing top-level module '{top_level_module}' for package '{pkg_name}': {e}")
            logging.error(traceback.format_exc())
            continue
    
    # Deduplicate other_relations
    for rel_type in ["INHERITS", "IMPORTS", "EXPOSES"]:
        combined_other_relations[rel_type] = list(set(combined_other_relations[rel_type]))
    
    logging.info(f"Completed processing package '{pkg_name}': "
                f"{len(all_entities)} total entities, {len(all_relations)} total relations")
    
    return all_entities, all_relations, combined_other_relations
