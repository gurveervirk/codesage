"""
COMExtractor (Code Object Model Extractor) Module

This module provides utilities to extract entities and relationships from Python modules and classes, such as:
- Modules
- Classes
- Methods
- Inheritance
- Imports

Primary API:
    process_package - Main entry point for analyzing Python packages
"""

# Primary API
from .core import (
    process_package,
    process_package_from_module_paths,
    get_top_level_module,
    get_top_level_modules_for_package
)

# Entity and Relationship models
from .models import Entity, Relationship, ExternalEntityRef, ExtractionResult

# Secondary/Internal API (for advanced users)
from .dynamic_analysis.processor import process_module

__all__ = [
    # Primary API
    "process_package",
    "process_package_from_module_paths",
    "get_top_level_module",
    "get_top_level_modules_for_package",
    # Models
    "Entity",
    "Relationship",
    "ExternalEntityRef",
    "ExtractionResult",
    # Secondary API
    "process_module",
]
