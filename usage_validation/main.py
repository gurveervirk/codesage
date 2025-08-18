import os
import ast
import re
import tempfile
import json
from typing import Dict, Any, Set, List, Tuple
from mypy import api
import stdlib_list

# ==============================================================================
# Step 1: Parse user code to find what external entities are being used.
# (This is the new, robust implementation that handles import aliases.)
# ==============================================================================
class ExternalUsageFinder(ast.NodeVisitor):
    """
    An AST visitor that finds all usages of external Python libraries in a given source code.

    This visitor performs static analysis to identify:
    1. Direct calls to functions or classes from external modules.
    2. Instantiations of classes from external modules.
    3. Method calls on variables that are instances of external classes.

    It correctly handles module and object aliasing and provides a list of
    fully-resolved, unaliased paths for each usage.
    """

    def __init__(self):
        # Use a set of standard library module names for efficient lookup
        self.standard_libs = set(stdlib_list.stdlib_list("3.13"))
        
        # Maps aliases or local names to their full import path
        # e.g., {'pd': 'pandas', 'train_test_split': 'sklearn.model_selection.train_test_split'}
        self.imported_modules = {}
        
        # Maps variable names to their inferred full class path
        # e.g., {'df': 'pandas.DataFrame'}
        self.tracked_variables = {}
        
        # A set to store the unique, fully-resolved usage paths found
        self.external_usages = set()

    def _is_external(self, module_name: str) -> bool:
        """Checks if a module is external by comparing it against the standard library list."""
        if not module_name:
            return False
        # Get the top-level module (e.g., 'sklearn' from 'sklearn.model_selection')
        root_module = module_name.split('.')[0]
        return root_module not in self.standard_libs

    def visit_Import(self, node: ast.Import):
        """Processes 'import <module>' and 'import <module> as <alias>' statements."""
        for alias in node.names:
            if self._is_external(alias.name):
                # Map the local name (alias or original) to the full module path
                self.imported_modules[alias.asname or alias.name] = alias.name
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        """Processes 'from <module> import <name>' and 'from <module> import <name> as <alias>'."""
        # Note: Relative imports (level > 0) are considered internal.
        if node.level == 0 and self._is_external(node.module):
            for alias in node.names:
                full_path = f"{node.module}.{alias.name}"
                # Map the local name (alias or original) to its full path
                self.imported_modules[alias.asname or alias.name] = full_path
        self.generic_visit(node)
        
    def _resolve_full_path(self, node: ast.AST) -> str | None:
        """
        Recursively resolves a dotted attribute chain (e.g., a.b.c) into a string.
        
        This handles nested attributes and names. It also includes a heuristic
        to trace through call chains, like `df.describe().transpose()`, by analyzing
        the function part of the inner call.
        """
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            parent_path = self._resolve_full_path(node.value)
            if parent_path:
                return f"{parent_path}.{node.attr}"
        elif isinstance(node, ast.Call):
            # Heuristic for chained calls: resolve the function being called.
            return self._resolve_full_path(node.func)
        return None

    def visit_Assign(self, node: ast.Assign):
        """
        Tracks variables that are assigned instances of external classes.
        e.g., df = pd.DataFrame()
        """
        # We are only interested in assignments where the value is a function/class call
        if isinstance(node.value, ast.Call):
            full_path = self._resolve_full_path(node.value.func)
            
            if full_path:
                parts = full_path.split('.')
                base = parts[0]
                
                # Check if the call originates from a known external module
                if base in self.imported_modules:
                    resolved_base = self.imported_modules[base]
                    # Reconstruct the full path without aliases
                    full_class_path = resolved_base if len(parts) == 1 else f"{resolved_base}.{'.'.join(parts[1:])}"
                    
                    # For simplicity, we handle single-target assignments (e.g., x = ...)
                    if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                        var_name = node.targets[0].id
                        # Track the variable name and its inferred type
                        self.tracked_variables[var_name] = full_class_path
        
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        """
        Identifies and resolves external function calls, class instantiations,
        and method calls on tracked objects.
        """
        full_path = self._resolve_full_path(node.func)
        if not full_path:
            self.generic_visit(node)
            return
            
        parts = full_path.split('.')
        base = parts[0]
        
        # Case 1: Method call on a tracked variable (e.g., 'df.info()')
        if base in self.tracked_variables:
            class_path = self.tracked_variables[base]
            method_path = '.'.join(parts[1:])
            # Reconstruct the full usage path
            full_usage = f"{class_path}.{method_path}" if method_path else class_path
            self.external_usages.add(full_usage)
            
        # Case 2: Direct call from an external module (e.g., 'pd.DataFrame()' or 'train_test_split()')
        elif base in self.imported_modules:
            resolved_base = self.imported_modules[base]
            # If the base itself was the imported object (from...import)
            if len(parts) == 1:
                full_usage = resolved_base
            # If the call is on an imported module (import...as)
            else:
                rest_of_path = '.'.join(parts[1:])
                full_usage = f"{resolved_base}.{rest_of_path}"
            self.external_usages.add(full_usage)
            
        self.generic_visit(node)
        
    def find_usages(self, source_code: str) -> list[str]:
        """
        Parses the source code and returns a list of all external library usages.
        """
        tree = ast.parse(source_code)
        self.visit(tree)
        return sorted(list(self.external_usages))

def find_external_entities(code: str) -> List[str]:
    """
    Parses Python code to find all external entity usages, resolving
    import aliases to their canonical paths.
    """
    try:
        finder = ExternalUsageFinder()
        return sorted(finder.find_usages(code))
    except SyntaxError:
        return []

# ==============================================================================
# Step 2: Generate a nested directory of .pyi stub files.
# ==============================================================================
TYPING_MEMBERS = {'Optional', 'Union', 'List', 'Dict', 'Any', 'Tuple', 'Callable', 'Set', 'Sequence', 'Iterable'}

def _extract_imports_from_signature(s: str) -> Tuple[Set[str], Set[str]]:
    m, t = set(), set()
    for tn in re.findall(r'[a-zA-Z_][\w\.]*', s):
        if tn in TYPING_MEMBERS: t.add(tn)
        if '.' in tn:
            mp, _ = tn.rsplit('.', 1)
            if mp == 'typing': t.add(_)
            else: m.add(mp.split('.')[0])
    return m, t

def _format_signature_for_pyi(s: str) -> str:
    """
    CORRECTED VERSION: This now preserves quotes for forward references and handles return type annotations.
    """
    if not s or s == '()': return '()'
    
    s = s.strip()
    return_annotation = ''
    if '->' in s:
        parts = s.rsplit('->', 1)
        s = parts[0].strip()
        return_annotation = f" -> {parts[1].strip()}"

    c = s[1:-1] # Remove outer parentheses from argument part
    
    p, cp, bl = [], '', 0
    for char in c:
        if char == ',' and bl == 0: p.append(cp.strip()); cp = ''
        else:
            if char in '([': bl += 1
            elif char in ')]': bl -= 1
            cp += char
    if cp:
        p.append(cp.strip())
        
    fp = []
    for param in p:
        if not param: continue
        np, _, dp = param.partition('=')
        n, _, th = np.strip().partition(':')
        n, th = n.strip(), th.strip() # Only strip whitespace, not quotes
        np_new = f"{n}: {th}" if th else n
        if dp: np_new += " = ..."
        fp.append(np_new)
        
    return f"({', '.join(fp)}){return_annotation}"

def generate_stub_directory(entities: Dict[str, Dict[str, Any]], root_stub_dir: str):
    file_contents: Dict[str, Dict[str, Any]] = {}

    # Sort entities to ensure classes are processed before their methods.
    sorted_entities = sorted(entities.items())

    for full_name, info in sorted_entities:
        if info is None: continue
        parts = full_name.split('.')
        entity_type = info.get("type", "").upper()

        module_parts = []
        class_name = None
        entity_name = ""

        if entity_type == "CLASS":
            module_parts, entity_name = parts[:-1], parts[-1]
        elif entity_type == "METHOD":
            module_parts, class_name, entity_name = parts[:-2], parts[-2], parts[-1]
        elif entity_type == "FUNCTION":
            module_parts, entity_name = parts[:-1], parts[-1]
        
        if not module_parts: continue
        stub_path = os.path.join(root_stub_dir, *module_parts) + ".pyi"
        
        if stub_path not in file_contents:
            file_contents[stub_path] = {"imports": set(), "typing": set(), "functions": [], "classes": {}}

        sig = info.get("signature", "()")
        m_imports, t_members = _extract_imports_from_signature(sig)
        file_contents[stub_path]["imports"].update(m_imports)
        file_contents[stub_path]["typing"].update(t_members)
        
        formatted_sig = _format_signature_for_pyi(sig)
        
        if entity_type == "FUNCTION":
            file_contents[stub_path]["functions"].append(f"def {entity_name}{formatted_sig}: ...")
        elif entity_type == "CLASS":
            if entity_name not in file_contents[stub_path]["classes"]:
                file_contents[stub_path]["classes"][entity_name] = {"init": "", "methods": []}
            file_contents[stub_path]["classes"][entity_name]["init"] = f"    def __init__{formatted_sig}: ..."
        elif entity_type == "METHOD" and class_name:
            if class_name not in file_contents[stub_path]["classes"]:
                file_contents[stub_path]["classes"][class_name] = {"init": "    ...", "methods": []}
            file_contents[stub_path]["classes"][class_name]["methods"].append(f"    def {entity_name}{formatted_sig}: ...")

    for path, content in file_contents.items():
        os.makedirs(os.path.dirname(path), exist_ok=True)
        import_lines = []
        if content["typing"]:
            import_lines.append(f"from typing import {', '.join(sorted(list(content['typing'])))}")
        other_mods = sorted([m for m in content["imports"] if m != 'typing'])
        import_lines.extend([f"import {m}" for m in other_mods])
        
        body_parts = []
        body_parts.extend(content["functions"])

        for class_name, class_content in sorted(content["classes"].items()):
            class_body = [f"class {class_name}:"]
            class_body.append(class_content.get("init", "    ..."))
            class_body.extend(sorted(class_content["methods"]))
            if len(class_body) == 1: # Class with no init or methods
                class_body.append("    ...")
            body_parts.append("\n".join(class_body))

        # Ensure the first line is # mypy: disable-error-code="name-defined"
        body_parts.insert(0, "# mypy: disable-error-code=\"name-defined\"")

        final_text = "\n".join(import_lines)
        if import_lines: final_text += "\n\n\n"
        final_text += "\n\n".join(body_parts) + "\n"
        
        final_text = final_text.replace('NoneType', 'None')
        # Unwrap ForwardRef('...') to '...'
        final_text = re.sub(r'ForwardRef\((["\'].*?["\'])\)', r'\1', final_text)

        with open(path, "w") as f: f.write(final_text)

# ==============================================================================
# Step 3: Main validation workflow
# ==============================================================================
def validate_code(user_code: str, signatures_dict: Dict[str, Dict[str, Any]]) -> str:
    output = []
    output.append("--- Starting Validation Process ---")
    output.append("--> Received Signatures:\n" + json.dumps(signatures_dict, indent=2))
    with tempfile.TemporaryDirectory() as temp_dir:
        stubs_path = os.path.join(temp_dir, "stubs")
        user_code_path = os.path.join(temp_dir, "user_code.py")
        config_path = os.path.join(temp_dir, "mypy.ini")

        with open(user_code_path, "w") as f:
            f.write(user_code)
        generate_stub_directory(signatures_dict, stubs_path)

        mypy_config_content = f"""
[mypy]
mypy_path = {stubs_path}
ignore_missing_imports = True
"""
        with open(config_path, "w") as f:
            f.write(mypy_config_content)
        
        output.append(f"--> Generated stubs and config in: {temp_dir}")
        output.append("--> Running mypy for validation...")
        # By default, mypy will use colors if it detects a TTY.
        # We can either pass --no-color-output or clean the output.
        # Cleaning is more robust if other tools add color.
        result = api.run(['--config-file', config_path, user_code_path])

        # Regex to remove ANSI escape codes (for colors, etc.)
        ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

        output.append("\n--- Validation Results ---")
        if result[0]:
            clean_stdout = ansi_escape.sub('', result[0])
            output.append("Found Validation Errors:\n")
            output.append(clean_stdout.replace(f'{user_code_path}:', 'Line '))
        if result[1]:
            clean_stderr = ansi_escape.sub('', result[1])
            output.append("Mypy System Error:\n" + clean_stderr)
        if result[2] == 0:
            output.append("Success! No validation errors found.")
        output.append("------------------------")
    return "\n".join(output)