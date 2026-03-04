"""
Tree-sitter based Python source code parser.
"""

import os
from typing import Dict, List, Optional, Any, Tuple
from tree_sitter import Node, Query, QueryCursor
from .tree_sitter_loader import get_python_parser, get_python_language

class PythonTreeSitterParser:
    def __init__(self):
        self.parser = get_python_parser()
        self.language = get_python_language()
        
        # Pre-compile queries
        self._compile_queries()

    def _compile_queries(self):
        # Imports
        self.import_query = Query(self.language, """
            (import_statement) @import
            (import_from_statement) @import_from
        """)

    def parse_file(self, file_path: str) -> Dict[str, Any]:
        """
        Parse a Python file and return a structured representation.
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
            
        with open(file_path, 'rb') as f:
            source_bytes = f.read()
            
        tree = self.parser.parse(source_bytes)
        root = tree.root_node
        
        # We return the file_path as provided. The caller is responsible for normalizing it.
        return {
            "file_path": file_path,
            "module_name": self._derive_module_name(file_path),
            "docstring": self._extract_docstring(root, source_bytes),
            "docstring_start_line": self._extract_docstring_span(root)[0],
            "docstring_end_line": self._extract_docstring_span(root)[1],
            "imports": self._extract_imports(root, source_bytes),
            "classes": self._extract_classes(root, source_bytes),
            "functions": self._extract_functions(root, source_bytes),
            "variables": self._extract_variables(root, source_bytes),
            "conditional_blocks": self._extract_conditional_blocks(root, source_bytes),
            "source_bytes": source_bytes,
            "source": source_bytes.decode('utf-8', errors='replace')
        }

    def _derive_module_name(self, file_path: str) -> str:
        """Simple filename based module name derivation. 
        Real resolution happens in upper layers."""
        base = os.path.basename(file_path)
        name, _ = os.path.splitext(base)
        return name

    def _extract_docstring(self, node: Node, source: bytes) -> Optional[str]:
        """
        Extract docstring from a module, class, or function node.
        """
        # Docstring is usually the first expression statement in the block/module
        if node.type == 'module':
            body = node
        elif node.type in ('class_definition', 'function_definition'):
             body = node.child_by_field_name('body')
        else:
            return None

        if not body:
            return None

        # Look for the first expression statement string
        for child in body.children:
            if child.type == 'expression_statement':
                # Check if it contains a string
                if child.child_count > 0 and child.children[0].type == 'string':
                    return self._node_text(child.children[0], source)
            elif child.type == 'comment':
                continue
            else:
                # If we hit valid code that isn't a docstring, stop
                break
        return None

    def _extract_docstring_span(self, node: Node) -> Tuple[Optional[int], Optional[int]]:
        if node.type == 'module':
            body = node
        elif node.type in ('class_definition', 'function_definition'):
            body = node.child_by_field_name('body')
        else:
            return None, None

        if not body:
            return None, None

        for child in body.children:
            if child.type == 'expression_statement':
                if child.child_count > 0 and child.children[0].type == 'string':
                    s = child.children[0].start_point.row + 1
                    e = child.children[0].end_point.row + 1
                    return s, e
            elif child.type == 'comment':
                continue
            else:
                break
        return None, None

    def _node_text(self, node: Node, source: bytes) -> str:
        if not node:
            return ""
        return source[node.start_byte:node.end_byte].decode('utf-8')

    def _extract_imports(self, root: Node, source: bytes) -> List[Dict[str, Any]]:
        imports = []
        cursor = QueryCursor(self.import_query)
        captures_dict = cursor.captures(root)
        captures = sorted([(n, name) for name, nodes in captures_dict.items() for n in nodes], key=lambda x: x[0].start_byte)
        
        # Deduplicate nodes because captures might return multiple matching patterns for same node
        # But here we have distinct capture names.
        
        for node, name in captures:
            if name == 'import':
                imports.append({
                    "type": "import",
                    "source": self._node_text(node, source),
                    "lineno": node.start_point.row + 1
                })
            elif name == 'import_from':
                 imports.append({
                    "type": "import_from",
                    "source": self._node_text(node, source),
                    "lineno": node.start_point.row + 1
                })
        return imports

    def _extract_classes(self, root: Node, source: bytes) -> List[Dict[str, Any]]:
        # Let's perform a recursive traversal on the AST for structural extraction
        # as it simplifies parent-child relationships which queries flatten.
        
        return self._traverse_block_for_classes(root, source)

    def _traverse_block_for_classes(self, block_node: Node, source: bytes) -> List[Dict[str, Any]]:
        classes = []
        
        # Iterate over children of the block
        for child in block_node.children:
            if child.type == 'class_definition':
                classes.append(self._process_class_node(child, source, []))
            elif child.type == 'decorated_definition':
                # Check if it wraps a class
                definition = child.child_by_field_name('definition')
                if definition and definition.type == 'class_definition':
                    decorators = self._extract_decorators(child, source)
                    classes.append(self._process_class_node(definition, source, decorators))
        
        return classes

    def _process_class_node(self, node: Node, source: bytes, decorators: List[str]) -> Dict[str, Any]:
        name_node = node.child_by_field_name('name')
        name = self._node_text(name_node, source)
        
        bases_node = node.child_by_field_name('superclasses')
        bases = []
        if bases_node:
            # bases_node is an argument_list (base1, base2)
            # We want the text of elements
             bases = [self._node_text(c, source) for c in bases_node.children if c.type not in (',', '(', ')')]

        body_node = node.child_by_field_name('body')
        
        methods = self._extract_functions(body_node, source) if body_node else []
        inner_classes = self._traverse_block_for_classes(body_node, source) if body_node else []
        class_variables = self._extract_variables(body_node, source) if body_node else []
        
        return {
            "name": name,
            "type": "CLASS",
            "lineno": node.start_point.row + 1,
            "end_lineno": node.end_point.row + 1,
            "docstring": self._extract_docstring(node, source),
            "docstring_start_line": self._extract_docstring_span(node)[0],
            "docstring_end_line": self._extract_docstring_span(node)[1],
            "signature_start_line": node.start_point.row + 1,
            "signature_end_line": (bases_node.end_point.row + 1) if bases_node else (name_node.end_point.row + 1),
            "decorators": decorators,
            "bases": bases,
            "methods": methods,
            "inner_classes": inner_classes,
            "class_variables": class_variables,
            "source": self._node_text(node, source)
        }

    def _extract_decorators(self, decorated_node: Node, source: bytes) -> List[str]:
        decorators = []
        for child in decorated_node.children:
            if child.type == 'decorator':
                decorators.append(self._node_text(child, source).strip())
        return decorators

    def _extract_functions(self, block_node: Node, source: bytes) -> List[Dict[str, Any]]:
        functions = []
        if not block_node:
            return functions

        for child in block_node.children:
            if child.type == 'function_definition':
                functions.append(self._process_function_node(child, source, []))
            elif child.type == 'decorated_definition':
                 definition = child.child_by_field_name('definition')
                 if definition and definition.type == 'function_definition':
                     decorators = self._extract_decorators(child, source)
                     functions.append(self._process_function_node(definition, source, decorators))
        return functions
        
    def _process_function_node(self, node: Node, source: bytes, decorators: List[str]) -> Dict[str, Any]:
        name_node = node.child_by_field_name('name')
        name = self._node_text(name_node, source)
        
        params_node = node.child_by_field_name('parameters')
        params_text = self._node_text(params_node, source)
        
        return_node = node.child_by_field_name('return_type')
        return_text = self._node_text(return_node, source) if return_node else None

        return {
            "name": name,
            "type": "FUNCTION",  # Context will determine if Method
            "lineno": node.start_point.row + 1,
            "end_lineno": node.end_point.row + 1,
            "docstring": self._extract_docstring(node, source),
            "docstring_start_line": self._extract_docstring_span(node)[0],
            "docstring_end_line": self._extract_docstring_span(node)[1],
            "signature_start_line": node.start_point.row + 1,
            "signature_end_line": (return_node.end_point.row + 1) if return_node else (params_node.end_point.row + 1),
            "decorators": decorators,
            "args": params_text, # Raw args for now
            "return_type": return_text,
            "source": self._node_text(node, source)
        }

    def _extract_variables(self, block_node: Node, source: bytes) -> List[Dict[str, Any]]:
        """Extract variable assignments from a block (module body or conditional branch body)."""
        variables = []
        if not block_node:
            return variables
        for child in block_node.children:
            if child.type == 'assignment':
                left = child.child_by_field_name('left')
                if left and left.type in ('pattern_list', 'tuple_pattern'):
                    right = child.child_by_field_name('right')
                    value_text = self._node_text(right, source) if right else None
                    for id_child in left.children:
                        if id_child.type == 'identifier':
                            name = self._node_text(id_child, source)
                            variables.append({
                                "name": name,
                                "value": value_text,
                                "type_annotation": None,
                                "lineno": child.start_point.row + 1,
                                "end_lineno": child.end_point.row + 1,
                                "is_all_caps": name.isupper() and len(name) > 0,
                                "is_augmented": False,
                                "is_type_alias": False,
                                "source": self._node_text(child, source),
                            })
                elif left and left.type == 'identifier':
                    name = self._node_text(left, source)
                    right = child.child_by_field_name('right')
                    value_text = self._node_text(right, source) if right else None
                    type_node = child.child_by_field_name('type')
                    type_text = self._node_text(type_node, source) if type_node else None
                    variables.append({
                        "name": name,
                        "value": value_text,
                        "type_annotation": type_text,
                        "lineno": child.start_point.row + 1,
                        "end_lineno": child.end_point.row + 1,
                        "is_all_caps": name.isupper() and len(name) > 0,
                        "is_augmented": False,
                        "is_type_alias": False,
                        "source": self._node_text(child, source),
                    })
            elif child.type == 'augmented_assignment':
                left = child.child_by_field_name('left')
                if left and left.type == 'identifier':
                    name = self._node_text(left, source)
                    right = child.child_by_field_name('right')
                    value_text = self._node_text(right, source) if right else None
                    op_node = child.child_by_field_name('operator')
                    op_text = self._node_text(op_node, source) if op_node else '+='
                    variables.append({
                        "name": name,
                        "value": value_text,
                        "operator": op_text,
                        "type_annotation": None,
                        "lineno": child.start_point.row + 1,
                        "end_lineno": child.end_point.row + 1,
                        "is_all_caps": name.isupper() and len(name) > 0,
                        "is_augmented": True,
                        "is_type_alias": False,
                        "source": self._node_text(child, source),
                    })
            elif child.type == 'type_alias_statement':
                name_node = child.child_by_field_name('name')
                value_node = child.child_by_field_name('value')
                if name_node:
                    name = self._node_text(name_node, source)
                    value_text = self._node_text(value_node, source) if value_node else None
                    variables.append({
                        "name": name,
                        "value": value_text,
                        "type_annotation": None,
                        "lineno": child.start_point.row + 1,
                        "end_lineno": child.end_point.row + 1,
                        "is_all_caps": name.isupper() and len(name) > 0,
                        "is_augmented": False,
                        "is_type_alias": True,
                        "source": self._node_text(child, source),
                    })
        return variables

    def _extract_conditional_blocks(self, block_node: Node, source: bytes, parent_start_line: Optional[int] = None) -> List[Dict[str, Any]]:
        """Extract top-level if/try-statement conditional blocks with their inner symbols."""
        blocks = []
        if not block_node:
            return blocks
        for child in block_node.children:
            if child.type == 'if_statement':
                blocks.extend(self._process_if_node(child, source, parent_start_line))
            elif child.type == 'try_statement':
                blocks.extend(self._process_try_node(child, source, parent_start_line))
        return blocks

    def _process_if_node(self, node: Node, source: bytes, parent_start_line: Optional[int] = None) -> List[Dict[str, Any]]:
        """Process an if/elif/else statement into a list of condition-branch dicts."""
        result = []
        node_start = node.start_point.row + 1
        condition_node = node.child_by_field_name('condition')
        condition_text = self._node_text(condition_node, source) if condition_node else "?"
        consequence_node = node.child_by_field_name('consequence')
        if consequence_node:
            result.append({
                "condition": condition_text,
                "branch": "if",
                "parent_block_start_line": parent_start_line,
                "imports": self._extract_imports(consequence_node, source),
                "classes": self._traverse_block_for_classes(consequence_node, source),
                "functions": self._extract_functions(consequence_node, source),
                "variables": self._extract_variables(consequence_node, source),
                "nested_blocks": self._extract_conditional_blocks(consequence_node, source, parent_start_line=node_start),
            })
        for child in node.children:
            if child.type == 'elif_clause':
                alt_cond_node = child.child_by_field_name('condition')
                alt_cond_text = self._node_text(alt_cond_node, source) if alt_cond_node else "?"
                alt_body = child.child_by_field_name('consequence')
                if alt_body:
                    result.append({
                        "condition": alt_cond_text,
                        "branch": "elif",
                        "parent_block_start_line": parent_start_line,
                        "imports": self._extract_imports(alt_body, source),
                        "classes": self._traverse_block_for_classes(alt_body, source),
                        "functions": self._extract_functions(alt_body, source),
                        "variables": self._extract_variables(alt_body, source),
                        "nested_blocks": self._extract_conditional_blocks(alt_body, source, parent_start_line=node_start),
                    })
            elif child.type == 'else_clause':
                alt_body = child.child_by_field_name('body')
                if alt_body:
                    result.append({
                        "condition": condition_text,
                        "branch": "else",
                        "parent_block_start_line": parent_start_line,
                        "imports": self._extract_imports(alt_body, source),
                        "classes": self._traverse_block_for_classes(alt_body, source),
                        "functions": self._extract_functions(alt_body, source),
                        "variables": self._extract_variables(alt_body, source),
                        "nested_blocks": self._extract_conditional_blocks(alt_body, source, parent_start_line=node_start),
                    })
        return result

    def _process_try_node(self, node: Node, source: bytes, parent_start_line: Optional[int] = None) -> List[Dict[str, Any]]:
        """Process a try/except/finally statement into a list of condition-branch dicts."""
        result = []
        node_start = node.start_point.row + 1
        body_node = node.child_by_field_name('body')
        if body_node:
            result.append({
                "condition": "try",
                "branch": "try",
                "parent_block_start_line": parent_start_line,
                "imports": self._extract_imports(body_node, source),
                "classes": self._traverse_block_for_classes(body_node, source),
                "functions": self._extract_functions(body_node, source),
                "variables": self._extract_variables(body_node, source),
                "nested_blocks": self._extract_conditional_blocks(body_node, source, parent_start_line=node_start),
            })
        for child in node.children:
            if child.type in ('except_clause', 'except_group_clause'):
                exc_parts = []
                body = None
                saw_except = False
                saw_colon = False
                for cc in child.children:
                    if cc.type == 'except':
                        saw_except = True
                        continue
                    if saw_except and not saw_colon:
                        if cc.type == ':':
                            saw_colon = True
                        elif cc.type == 'block':
                            body = cc
                            saw_colon = True
                        else:
                            exc_parts.append(self._node_text(cc, source).strip())
                    elif saw_colon and cc.type == 'block':
                        body = cc
                exc_text = ' '.join(p for p in exc_parts if p and p not in ('as',))
                cond = f"except {exc_text}".strip() if exc_text else "except"
                if body:
                    result.append({
                        "condition": cond,
                        "branch": "except",
                        "parent_block_start_line": parent_start_line,
                        "imports": self._extract_imports(body, source),
                        "classes": self._traverse_block_for_classes(body, source),
                        "functions": self._extract_functions(body, source),
                        "variables": self._extract_variables(body, source),
                        "nested_blocks": self._extract_conditional_blocks(body, source, parent_start_line=node_start),
                    })
            elif child.type == 'else_clause':
                alt_body = child.child_by_field_name('body')
                if alt_body:
                    result.append({
                        "condition": "try_else",
                        "branch": "else",
                        "parent_block_start_line": parent_start_line,
                        "imports": self._extract_imports(alt_body, source),
                        "classes": self._traverse_block_for_classes(alt_body, source),
                        "functions": self._extract_functions(alt_body, source),
                        "variables": self._extract_variables(alt_body, source),
                        "nested_blocks": self._extract_conditional_blocks(alt_body, source, parent_start_line=node_start),
                    })
            elif child.type == 'finally_clause':
                fin_body = None
                for cc in child.children:
                    if cc.type == 'block':
                        fin_body = cc
                if fin_body:
                    result.append({
                        "condition": "finally",
                        "branch": "finally",
                        "parent_block_start_line": parent_start_line,
                        "imports": self._extract_imports(fin_body, source),
                        "classes": self._traverse_block_for_classes(fin_body, source),
                        "functions": self._extract_functions(fin_body, source),
                        "variables": self._extract_variables(fin_body, source),
                        "nested_blocks": self._extract_conditional_blocks(fin_body, source, parent_start_line=node_start),
                    })
        return result
