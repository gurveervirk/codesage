"""
Tree-sitter language loader and parser initialization.
"""

from tree_sitter import Language, Parser
import tree_sitter_python

def get_python_parser() -> Parser:
    """
    Get a configured Tree-sitter parser for Python.
    """
    PY_LANGUAGE = Language(tree_sitter_python.language())
    parser = Parser(PY_LANGUAGE)
    return parser

def get_python_language() -> Language:
    """
    Get the Python language definition.
    """
    return Language(tree_sitter_python.language())
