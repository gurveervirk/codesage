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
            "source": self._node_text(node, source) # Full class source
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

