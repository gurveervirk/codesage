"""
Script to create test files from GitChameleon dataset for Cline testing.

This script reads current_tests.csv to get library-version pairs, then reads
the dataset.jsonl file and creates individual test files in a single 'tests' 
folder for only those matching pairs.

Each test file (sample_{i}.py) contains:
- Problem statement and metadata as comments
- Starting code to complete

The script also logs tested pairs to tested_pairs.csv for deduplication tracking.
"""

import json
import csv
from pathlib import Path
from typing import Dict, Any, Set, Tuple


def normalize_version(version: str) -> str:
    """
    Normalize version string to match the format in current_tests.csv.
    Converts "4.28" to "version_4_28" format.
    
    Args:
        version: Version string (e.g., "4.28", "3.0.0")
    
    Returns:
        Normalized version label (e.g., "version_4_28", "version_3_0_0")
    """
    if version.startswith("version_"):
        return version
    return f"version_{version.replace('.', '_').replace(':', '_').replace('-', '_')}"


def read_current_tests(csv_path: Path) -> Set[Tuple[str, str]]:
    """
    Read library-version pairs from current_tests.csv.
    
    Args:
        csv_path: Path to current_tests.csv
    
    Returns:
        Set of (library, version_label) tuples
    """
    pairs = set()
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            library = row['root_module_name'].strip()
            version_label = row['label'].strip()
            pairs.add((library, version_label))
    return pairs


def read_tested_pairs(csv_path: Path) -> Set[Tuple[str, str]]:
    """
    Read already tested library-version pairs from tested_pairs.csv.
    
    Args:
        csv_path: Path to tested_pairs.csv
    
    Returns:
        Set of (library, version_label) tuples
    """
    if not csv_path.exists():
        return set()
    
    pairs = set()
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            library = row['root_module_name'].strip()
            version_label = row['label'].strip()
            pairs.add((library, version_label))
    return pairs


def append_tested_pairs(csv_path: Path, pairs: Set[Tuple[str, str]]) -> None:
    """
    Append newly tested pairs to tested_pairs.csv.
    
    Args:
        csv_path: Path to tested_pairs.csv
        pairs: Set of (library, version_label) tuples to append
    """
    file_exists = csv_path.exists()
    
    with open(csv_path, 'a', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        
        # Write header if file doesn't exist
        if not file_exists:
            writer.writerow(['root_module_name', 'label'])
        
        # Write pairs sorted for consistency
        for library, version_label in sorted(pairs):
            writer.writerow([library, version_label])


def clear_tests_folder(output_dir: Path) -> None:
    """
    Clear the tests folder by removing all files in it.
    
    Args:
        output_dir: Path to the tests directory
    """
    if output_dir.exists():
        # Remove all files in the directory
        for file_path in output_dir.glob('*'):
            if file_path.is_file():
                file_path.unlink()
        print(f"✓ Cleared existing test files in {output_dir}")
    else:
        output_dir.mkdir(parents=True, exist_ok=True)
        print(f"✓ Created tests directory: {output_dir}")


def create_test_file(example: Dict[str, Any], file_path: Path) -> None:
    """
    Create a test file with problem description and starting code.
    
    Format (as per Figure 21):
    # Complete using the following libraries and/or extra dependencies and their versions:
    # problem statement: {problem}
    # library: {library}
    # version: {version}
    {starting_code}
    """
    content = f"""# Complete using the following libraries and/or extra dependencies and their versions:
# problem statement: {example['problem']}
# library: {example['library']}
# version: {example['version']}
{example['starting_code']}"""
    
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)
        
def create_test_folder(dataset_path: str, output_dir: str, current_tests_pairs: Set[Tuple[str, str]]) -> Set[Tuple[str, str]]:
    """
    Main function to create test files from the dataset for specified library-version pairs.
    
    Args:
        dataset_path: Path to the dataset.jsonl file
        output_dir: Directory where test files will be created
        current_tests_pairs: Set of (library, version_label) tuples to create tests for
    
    Returns:
        Set of (library, version_label) tuples that were actually created
    """
    dataset_path = Path(dataset_path)
    output_dir = Path(output_dir)
    
    # Clear the tests folder before creating new files
    clear_tests_folder(output_dir)
    
    files_created = 0
    
    # Read and process each line in the JSONL file
    with open(dataset_path, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            try:
                example = json.loads(line.strip())
                
                # Extract library and version
                library = example.get('library', '').strip()
                version = example.get('version', '').strip()
                version_label = normalize_version(version)
                
                # Check if this pair is in our current_tests list
                if (library, version_label) not in current_tests_pairs:
                    continue
                
                # Create file name using example_id: sample_0.py, sample_1.py, etc.
                example_id = example.get('example_id', str(line_num - 1))
                file_name = f"sample_{example_id}.py"
                file_path = output_dir / file_name
                
                # Create test file
                create_test_file(example, file_path)
                files_created += 1
                
                print(f"✓ Created test file: {file_name} (library: {library}, version: {version})")
                
            except json.JSONDecodeError as e:
                print(f"✗ Error parsing line {line_num}: {e}")
            except Exception as e:
                print(f"✗ Error creating test file for line {line_num}: {e}")
    
    print(f"\n✓ Test file creation complete!")
    print(f"  Output directory: {output_dir}")
    print(f"  Total files created: {files_created}")
    print(f"  Library-version pairs from current_tests.csv: {len(current_tests_pairs)}")
    
    return current_tests_pairs


def main():
    """
    Main entry point for the script.
    """
    # Get the directory where this script is located
    script_dir = Path(__file__).parent
    
    # Define paths
    dataset_path = script_dir.parent.parent.parent.parent / "GitChameleonBenchmark" / "dataset" / "dataset.jsonl"
    output_dir = script_dir.parent / "tests"
    current_tests_csv = script_dir / "current_tests.csv"
    tested_pairs_csv = script_dir / "tested_pairs.csv"
    
    print("GitChameleon Test File Generator")
    print("=" * 50)
    print(f"Dataset: {dataset_path}")
    print(f"Current tests CSV: {current_tests_csv}")
    print(f"Output: {output_dir}")
    print(f"Tested pairs log: {tested_pairs_csv}")
    print("=" * 50)
    print()
    
    # Check if dataset exists
    if not dataset_path.exists():
        print(f"✗ Error: Dataset file not found at {dataset_path}")
        print("  Please ensure the dataset.jsonl file is in the correct location.")
        return
    
    # Check if current_tests.csv exists
    if not current_tests_csv.exists():
        print(f"✗ Error: current_tests.csv not found at {current_tests_csv}")
        print("  Please ensure the current_tests.csv file is in the correct location.")
        return
    
    # Read current tests pairs
    print("Reading library-version pairs from current_tests.csv...")
    current_tests_pairs = read_current_tests(current_tests_csv)
    print(f"✓ Found {len(current_tests_pairs)} library-version pairs to test")
    
    # Read already tested pairs
    print("Checking for previously tested pairs...")
    already_tested = read_tested_pairs(tested_pairs_csv)
    if already_tested:
        print(f"✓ Found {len(already_tested)} previously tested pairs")
        # Filter out already tested pairs
        new_pairs = current_tests_pairs - already_tested
        if not new_pairs:
            print("✓ All pairs have already been tested!")
            return
        print(f"✓ {len(new_pairs)} new pairs to test")
        current_tests_pairs = new_pairs
    else:
        print("✓ No previously tested pairs found")
    
    print()
    
    # Create test folders
    created_pairs = create_test_folder(str(dataset_path), str(output_dir), current_tests_pairs)
    
    # Log the tested pairs
    if created_pairs:
        print(f"\n✓ Logging {len(created_pairs)} tested pairs to {tested_pairs_csv}")
        append_tested_pairs(tested_pairs_csv, created_pairs)
        print("✓ Testing session complete!")
    else:
        print("\n✗ No test files were created (no matching library-version pairs found in dataset)")


if __name__ == "__main__":
    main()
