"""
Utility functions for COMExtractor.
"""

from .diff_compare import compare_extractions
from .analyze_comparison import analyze_name_diffs
from .general_utils import extract_simple_name

__all__ = [
    'compare_extractions', 
    'analyze_name_diffs',
    'extract_simple_name'
]