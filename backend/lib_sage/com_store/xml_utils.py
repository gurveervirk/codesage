"""
XML utility functions for formatting responses.
"""
import xml.etree.ElementTree as ET
from xml.dom import minidom
from typing import Dict, Any


def _escape_xml(text: str) -> str:
    """Escape special XML characters in text."""
    if text is None:
        return ""
    text = str(text)
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    text = text.replace('"', "&quot;")
    text = text.replace("'", "&apos;")
    return text


def dict_to_xml_string(data: Dict[str, Any], root_tag: str = "response") -> str:
    """
    Convert a dictionary to a formatted XML string.
    
    Args:
        data: Dictionary to convert
        root_tag: Root element tag name
        
    Returns:
        Formatted XML string
    """
    def _add_element(parent: ET.Element, key: str, value: Any) -> None:
        """Recursively add elements to the XML tree."""
        if value is None:
            elem = ET.SubElement(parent, key)
            elem.text = ""
        elif isinstance(value, dict):
            elem = ET.SubElement(parent, key)
            for k, v in value.items():
                _add_element(elem, k, v)
        elif isinstance(value, list):
            elem = ET.SubElement(parent, key)
            for item in value:
                if isinstance(item, dict):
                    item_elem = ET.SubElement(elem, "item")
                    for k, v in item.items():
                        _add_element(item_elem, k, v)
                else:
                    item_elem = ET.SubElement(elem, "item")
                    item_elem.text = _escape_xml(item)
        else:
            elem = ET.SubElement(parent, key)
            elem.text = _escape_xml(value)
    
    root = ET.Element(root_tag)
    for key, value in data.items():
        _add_element(root, key, value)
    
    # Convert to string with pretty formatting
    xml_str = ET.tostring(root, encoding='unicode')
    
    # Parse and pretty print
    dom = minidom.parseString(xml_str)
    return dom.toprettyxml(indent="  ")
