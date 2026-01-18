"""
General utility functions for com_extractor.
"""

def extract_simple_name(name: str) -> str:
    """
    Extract the final part of a dot-separated name.
    
    Args:
        name: A dot-separated name (e.g., 'module.submodule.Class')
        
    Returns:
        The last component of the name (e.g., 'Class')
    """
    if not name:
        return ""
    return name.split(".")[-1]
