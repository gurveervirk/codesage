"""
Utility functions for COMStore operations.
"""
import re
from typing import List, Any


def _escape_regex_special_chars(text: str) -> str:
    r"""
    Escape special regex characters in a string for use in Cypher regex patterns.
    
    This escapes characters that have special meaning in regex: . ^ $ * + ? { } [ ] \ | ( )
    
    Args:
        text: String that may contain regex special characters
        
    Returns:
        String with regex special characters escaped
    """
    return re.escape(text)


def _extract_partial_terms(term: str) -> List[str]:
    """
    Extract partial search terms from a potentially fully-qualified name.
    
    For example, 'mod.mod2.entity' would return ['entity', 'mod2.entity', 'mod.mod2.entity']
    This allows finding entities by their simple name or partial path even if the full path doesn't exist.
    
    Args:
        term: Search term (potentially a dotted path)
        
    Returns:
        List of progressively longer partial terms, starting from the rightmost component
    """
    if '.' not in term:
        return [term]
    
    parts = term.split('.')
    partial_terms = []
    
    # Build from right to left: entity, mod2.entity, mod.mod2.entity
    for i in range(len(parts)):
        partial = '.'.join(parts[i:])
        partial_terms.append(partial)
    
    # Reverse to get longest matches first (prefer more specific matches)
    return list(reversed(partial_terms))


def check_if_not_null(props: List[str], values: List[Any]) -> None:
    """Check if variable is not null and raise error accordingly."""
    for prop, value in zip(props, values):
        if not value:
            raise ValueError(f"Parameter `{prop}` must not be None or empty string")
