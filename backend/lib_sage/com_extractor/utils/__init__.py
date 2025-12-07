"""
Utility functions for COMExtractor.
"""

from .diff_compare import compare_extractions
from .analyze_comparison import analyze_name_diffs

__all__ = [
    'compare_extractions', 
    'analyze_name_diffs'
]