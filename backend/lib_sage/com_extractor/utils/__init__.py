"""
Utility functions for COMExtractor.
"""

from .diff_compare import compare_extractions
from .analyze_comparison import analyze_name_diffs
from .decorator_utils import get_function_method_labels, _resolve_decorator_details
from .overload_utils import get_overloads_with_fallback
from .signature_utils import get_typed_signature, _normalize_signature
from .source_utils import safe_get_source, safe_get_docstring, get_import_statements
from .general_utils import extract_simple_name

__all__ = [
    'compare_extractions', 
    'analyze_name_diffs',
    'get_function_method_labels',
    '_resolve_decorator_details',
    'get_overloads_with_fallback',
    'get_typed_signature',
    '_normalize_signature',
    'safe_get_source',
    'safe_get_docstring',
    'get_import_statements',
    'extract_simple_name'
]