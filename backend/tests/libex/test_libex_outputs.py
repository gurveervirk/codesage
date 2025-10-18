"""
Pytest suite for testing library extraction outputs against expected results.

This module compares generated outputs from libex functions against pre-generated
expected outputs stored in JSON files.
"""

import json
import pytest
from pathlib import Path
from typing import Dict, Any, List

from .utils import generate_outputs, set_decoder


# Get test directories
TESTS_DIR = Path(__file__).parent
TEST_JSONS_DIR = TESTS_DIR / "test_jsons"
EXPECTED_OUTPUTS_DIR = TESTS_DIR / "expected_outputs"


def get_test_cases() -> List[tuple]:
    """
    Discover all test cases by finding matching test JSON and expected output files.
    
    Returns:
        List of tuples containing (test_name, config_path, expected_path)
    """
    test_cases = []
    
    if not TEST_JSONS_DIR.exists():
        return test_cases
    
    for json_file in TEST_JSONS_DIR.glob("*.json"):
        expected_file = EXPECTED_OUTPUTS_DIR / f"{json_file.stem}_expected.json"
        
        if expected_file.exists():
            test_cases.append((
                json_file.stem,
                json_file,
                expected_file
            ))
    
    return test_cases


def _is_non_deterministic_value(value: Any) -> bool:
    """
    Check if a value is non-deterministic (memory addresses, object instances, etc.).
    
    Args:
        value: The value to check
    
    Returns:
        True if the value is non-deterministic and should be ignored in comparisons
    """
    if not isinstance(value, str):
        return False
    
    # Check for our placeholder format
    if value.startswith("<NON_DETERMINISTIC:"):
        return True
    
    # Check for object memory addresses (fallback for old format)
    if " object at 0x" in value:
        return True
    
    # Check for ModuleSpec with memory addresses (fallback for old format)
    if value.startswith("ModuleSpec(") and " object at 0x" in value:
        return True
    
    return False


def _normalize_non_deterministic_value(value: Any) -> Any:
    """
    Normalize non-deterministic values to a comparable format.
    
    Args:
        value: The value to normalize
    
    Returns:
        Normalized value or original if not non-deterministic
    """
    if not isinstance(value, str):
        return value
    
    # If already in placeholder format, return as-is
    if value.startswith("<NON_DETERMINISTIC:"):
        return value
    
    # Convert old format to new placeholder format
    if " object at 0x" in value:
        obj_type = value.split(" object at ")[0].lstrip("<")
        return f"<NON_DETERMINISTIC:{obj_type}>"
    
    if value.startswith("ModuleSpec(") and " object at 0x" in value:
        import re
        match = re.search(r"name='([^']+)'", value)
        if match:
            module_name = match.group(1)
            return f"<NON_DETERMINISTIC:ModuleSpec(name='{module_name}')>"
        return "<NON_DETERMINISTIC:ModuleSpec>"
    
    return value


def _normalize_set_value(value: Any) -> Any:
    """
    Normalize set values by converting them to sorted tuples for consistent comparison.
    Using tuples instead of lists to make them hashable for set comparison.
    
    Args:
        value: The value to normalize
    
    Returns:
        Normalized value (sets converted to sorted tuples)
    """
    if isinstance(value, set):
        try:
            return tuple(sorted(value))
        except TypeError:
            # If items aren't sortable, convert to tuple and sort by string representation
            return tuple(sorted(value, key=str))
    return value


def compare_outputs(generated: Dict[str, Any], expected: Dict[str, Any], path: str = "") -> List[str]:
    """
    Recursively compare generated and expected outputs.
    Ignores non-deterministic values like memory addresses and normalizes sets.
    
    Args:
        generated: Generated output dictionary
        expected: Expected output dictionary
        path: Current path in the nested structure (for error reporting)
    
    Returns:
        List of difference descriptions
    """
    differences = []
    
    # Normalize values if they're sets
    expected = _normalize_set_value(expected)
    generated = _normalize_set_value(generated)
    
    # Check if both are dictionaries
    if isinstance(expected, dict) and isinstance(generated, dict):
        # Check for missing keys in generated
        for key in expected:
            current_path = f"{path}.{key}" if path else key
            
            if key not in generated:
                differences.append(f"Missing key: {current_path}")
            else:
                # Recursively compare nested structures
                differences.extend(compare_outputs(
                    generated[key],
                    expected[key],
                    current_path
                ))
        
        # Check for extra keys in generated
        for key in generated:
            current_path = f"{path}.{key}" if path else key
            
            if key not in expected:
                differences.append(f"Extra key: {current_path}")
    
    # Check if both are lists
    elif isinstance(expected, list) and isinstance(generated, list):
        if len(expected) != len(generated):
            differences.append(
                f"{path}: List length mismatch (expected {len(expected)}, got {len(generated)})"
            )
        else:
            for i, (exp_item, gen_item) in enumerate(zip(expected, generated)):
                current_path = f"{path}[{i}]"
                differences.extend(compare_outputs(gen_item, exp_item, current_path))
    
    # Compare primitive values
    else:
        # Normalize non-deterministic values before comparison
        expected_normalized = _normalize_non_deterministic_value(expected)
        generated_normalized = _normalize_non_deterministic_value(generated)
        
        if expected_normalized != generated_normalized:
            differences.append(
                f"{path}: Value mismatch\n"
                f"  Expected: {expected_normalized}\n"
                f"  Got:      {generated_normalized}"
            )
    
    return differences


@pytest.mark.parametrize("test_name,config_path,expected_path", get_test_cases())
def test_entity_outputs(test_name: str, config_path: Path, expected_path: Path):
    """
    Test that generated outputs match expected outputs for each test case.
    
    Args:
        test_name: Name of the test (from JSON filename)
        config_path: Path to the test configuration JSON
        expected_path: Path to the expected output JSON
    """
    # Load configuration
    with open(config_path, "r") as f:
        config = json.load(f)
    
    # Load expected outputs (with set decoder)
    with open(expected_path, "r") as f:
        expected = json.load(f, object_hook=set_decoder)
    
    # Generate outputs
    generated = generate_outputs(config)
    
    # Compare outputs
    differences = compare_outputs(generated, expected)
    
    # Assert no differences
    if differences:
        error_msg = f"\n{test_name} outputs do not match expected:\n"
        error_msg += "\n".join(f"  - {diff}" for diff in differences)
        pytest.fail(error_msg)


def test_typed_signature_format():
    """
    Test that typed signatures are in the expected format.
    """
    test_cases = get_test_cases()
    
    if not test_cases:
        pytest.skip("No test cases found")
    
    for test_name, _, expected_path in test_cases:
        with open(expected_path, "r") as f:
            expected = json.load(f)
        
        for entity_path, entity_output in expected.get("outputs", {}).items():
            typed_sig = entity_output.get("typed_signature")
            
            # Check that typed signature exists and is a string
            assert typed_sig is not None, f"{test_name}: {entity_path} missing typed_signature"
            assert isinstance(typed_sig, str), f"{test_name}: {entity_path} typed_signature is not a string"
            
            # Check it's not an error (unless expected to be)
            if not entity_output.get("error"):
                assert not typed_sig.startswith("Error:"), \
                    f"{test_name}: {entity_path} typed_signature contains error: {typed_sig}"


def test_labels_format():
    """
    Test that labels are in the expected format.
    """
    test_cases = get_test_cases()
    
    if not test_cases:
        pytest.skip("No test cases found")
    
    valid_labels = {
        "PUBLIC", "PRIVATE", "PROTECTED", "DUNDER",
        "ASYNC", "GENERATOR", "PROPERTY", "STATICMETHOD", "CLASSMETHOD"
    }
    
    for test_name, _, expected_path in test_cases:
        with open(expected_path, "r") as f:
            expected = json.load(f)
        
        for entity_path, entity_output in expected.get("outputs", {}).items():
            labels = entity_output.get("labels", [])
            
            # Check that labels is a list
            assert isinstance(labels, list), \
                f"{test_name}: {entity_path} labels is not a list"
            
            # Check each label is a string
            for label in labels:
                assert isinstance(label, str), \
                    f"{test_name}: {entity_path} contains non-string label: {label}"
                
                # Check if it's a known label or version label
                if not label.startswith("version:"):
                    # Allow unknown labels but warn in this case
                    pass


def test_decorators_format():
    """
    Test that decorators are in the expected format.
    """
    test_cases = get_test_cases()
    
    if not test_cases:
        pytest.skip("No test cases found")
    
    for test_name, _, expected_path in test_cases:
        with open(expected_path, "r") as f:
            expected = json.load(f)
        
        for entity_path, entity_output in expected.get("outputs", {}).items():
            decorators = entity_output.get("decorators", [])
            
            # Check that decorators is a list
            assert isinstance(decorators, list), \
                f"{test_name}: {entity_path} decorators is not a list"
            
            # Check each decorator is a string
            for decorator in decorators:
                assert isinstance(decorator, str), \
                    f"{test_name}: {entity_path} contains non-string decorator: {decorator}"


def test_overloads_format():
    """
    Test that overloads are in the expected format.
    """
    test_cases = get_test_cases()
    
    if not test_cases:
        pytest.skip("No test cases found")
    
    for test_name, _, expected_path in test_cases:
        with open(expected_path, "r") as f:
            expected = json.load(f)
        
        for entity_path, entity_output in expected.get("outputs", {}).items():
            overloads = entity_output.get("overloads", [])
            
            # Check that overloads is a list
            assert isinstance(overloads, list), \
                f"{test_name}: {entity_path} overloads is not a list"
            
            # Check each overload has required fields
            for i, overload in enumerate(overloads):
                assert isinstance(overload, dict), \
                    f"{test_name}: {entity_path} overload[{i}] is not a dict"
                
                assert "signature" in overload, \
                    f"{test_name}: {entity_path} overload[{i}] missing 'signature'"
                
                assert "name" in overload, \
                    f"{test_name}: {entity_path} overload[{i}] missing 'name'"
                
                assert isinstance(overload["signature"], str), \
                    f"{test_name}: {entity_path} overload[{i}] signature is not a string"
                
                assert isinstance(overload["name"], str), \
                    f"{test_name}: {entity_path} overload[{i}] name is not a string"


def test_namespaces_format():
    """
    Test that namespaces are in the expected format.
    """
    test_cases = get_test_cases()
    
    if not test_cases:
        pytest.skip("No test cases found")
    
    for test_name, _, expected_path in test_cases:
        with open(expected_path, "r") as f:
            expected = json.load(f)
        
        for entity_path, entity_output in expected.get("outputs", {}).items():
            namespaces = entity_output.get("namespaces", {})
            runtime_ns = entity_output.get("runtime_namespaces", {})
            
            # Check that namespaces is a dict
            assert isinstance(namespaces, dict), \
                f"{test_name}: {entity_path} namespaces is not a dict"
            
            # Check that runtime_namespaces is a dict
            assert isinstance(runtime_ns, dict), \
                f"{test_name}: {entity_path} runtime_namespaces is not a dict"
            
            # Check that all values in namespaces are strings (serialized) or sets (in JSON format)
            for key, value in namespaces.items():
                assert isinstance(key, str), \
                    f"{test_name}: {entity_path} namespaces has non-string key: {key}"
                
                # Value can be a string, a set (loaded from JSON), or a dict with __set__ key
                if isinstance(value, dict) and "__set__" in value:
                    # This is a serialized set before decoding
                    assert isinstance(value["__set__"], list), \
                        f"{test_name}: {entity_path} namespaces[{key}] has invalid set format"
                elif isinstance(value, set):
                    # This is a decoded set (if set_decoder was used)
                    pass
                else:
                    # Should be a string
                    assert isinstance(value, str), \
                        f"{test_name}: {entity_path} namespaces[{key}] is not a string or set (got {type(value).__name__})"
            
            # Check that all values in runtime_namespaces are strings
            for key, value in runtime_ns.items():
                assert isinstance(key, str), \
                    f"{test_name}: {entity_path} runtime_namespaces has non-string key: {key}"
                assert isinstance(value, str), \
                    f"{test_name}: {entity_path} runtime_namespaces[{key}] is not a string"


def test_output_structure():
    """
    Test that the overall output structure is correct.
    """
    test_cases = get_test_cases()
    
    if not test_cases:
        pytest.skip("No test cases found")
    
    for test_name, _, expected_path in test_cases:
        with open(expected_path, "r") as f:
            expected = json.load(f)
        
        # Check top-level keys
        assert "library" in expected, f"{test_name}: missing 'library' key"
        assert "version" in expected, f"{test_name}: missing 'version' key"
        assert "outputs" in expected, f"{test_name}: missing 'outputs' key"
        
        # Check types
        assert isinstance(expected["library"], str), \
            f"{test_name}: 'library' is not a string"
        assert isinstance(expected["version"], str), \
            f"{test_name}: 'version' is not a string"
        assert isinstance(expected["outputs"], dict), \
            f"{test_name}: 'outputs' is not a dict"


def test_no_missing_expected_outputs():
    """
    Test that all test JSON files have corresponding expected output files.
    """
    if not TEST_JSONS_DIR.exists():
        pytest.skip("Test JSONs directory does not exist")
    
    missing = []
    
    for json_file in TEST_JSONS_DIR.glob("*.json"):
        expected_file = EXPECTED_OUTPUTS_DIR / f"{json_file.stem}_expected.json"
        
        if not expected_file.exists():
            missing.append(json_file.name)
    
    if missing:
        pytest.fail(
            f"Missing expected output files for: {', '.join(missing)}\n"
            f"Run prepare_tests.py to generate them."
        )


# Run this if no test cases exist to provide helpful message
def pytest_collection_modifyitems(items):
    """
    Custom pytest hook to skip tests when no test cases are found.
    """
    if not get_test_cases():
        for item in items:
            if item.name.startswith("test_entity_outputs"):
                item.add_marker(
                    pytest.mark.skip(
                        reason="No test cases found. Add JSON files to test_jsons/ and run prepare_tests.py"
                    )
                )
