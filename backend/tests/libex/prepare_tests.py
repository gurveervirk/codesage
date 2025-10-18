"""
Prepare expected outputs for library entities for testing.

This module provides functionality to:
- Install libraries in temporary virtual environments
- Extract typed signatures, function/method labels, overloads, and namespaces
- Generate structured output dictionaries for testing
"""
from pathlib import Path
import json

# Set correct path to import lib_sage
import sys
sys.path.append(str(Path(__file__).parent.parent.parent))

from utils import generate_outputs, SetEncoder
import argparse

def prepare_tests(override: bool = False):
    """
    Check `test_jsons/` folder for new tests and generate expected outputs and store them.
    
    Args:
        override: If True, regenerate all expected outputs even if they exist.
                  If False, only generate outputs for new tests without expected outputs.
    """
    tests_dir = Path(__file__).parent
    jsons_dir = tests_dir / "test_jsons"
    output_dir = tests_dir / "expected_outputs"
    
    # Ensure output directory exists
    output_dir.mkdir(exist_ok=True)
    
    test_files = list(jsons_dir.glob("*.json"))
    
    if not test_files:
        print("No test JSON files found in test_jsons/")
        return
    
    print(f"Found {len(test_files)} test file(s) to process...")
    if override:
        print("Override mode: Will regenerate ALL expected outputs\n")
    else:
        print("Normal mode: Will only generate missing expected outputs\n")
    
    processed = 0
    skipped = 0
    errors = 0
    
    for json_file in test_files:
        output_file = output_dir / f"{json_file.stem}_expected.json"
        
        # Skip if output exists and override is False
        if output_file.exists() and not override:
            print(f"⊘ Skipping: {json_file.name} (expected output already exists)")
            skipped += 1
            continue
        
        print(f"\n{'Regenerating' if override and output_file.exists() else 'Processing'}: {json_file.name}")
        
        try:
            with open(json_file, "r") as f:
                config = json.load(f)
            
            print(f"  Library: {config.get('library')} v{config.get('version', 'latest')}")
            print(f"  Entities: {len(config.get('entities', []))}")
            
            outputs = generate_outputs(config)

            with open(output_file, "w") as f:
                json.dump(outputs, f, indent=4, sort_keys=True, cls=SetEncoder)
            
            print(f"  ✓ Generated: {output_file.name}")
            processed += 1
            
        except Exception as e:
            print(f"  ✗ Error: {e}")
            errors += 1
            import traceback
            traceback.print_exc()
    
    print(f"\n{'='*60}")
    print(f"Summary:")
    print(f"  Processed: {processed}")
    print(f"  Skipped:   {skipped}")
    print(f"  Errors:    {errors}")
    print(f"{'='*60}")
    
    if skipped > 0 and not override:
        print(f"\nTo regenerate existing outputs, run with --override flag")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate expected outputs for libex tests"
    )
    parser.add_argument(
        "--override",
        action="store_true",
        help="Regenerate all expected outputs, even if they already exist"
    )
    
    args = parser.parse_args()
    prepare_tests(override=args.override)