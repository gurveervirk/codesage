#!/usr/bin/env python3
"""
Helper script to extract version information from GitChameleon dataset.

This script extracts:
1. All Python versions being used
2. Main library versions as a list
3. Library version + additional dependencies
4. Complete environment (library + additional deps + python version)
"""

import json
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Set


def parse_dependencies(dep_string: str) -> List[Dict[str, str]]:
    """
    Parse dependency string into structured format.
    
    Args:
        dep_string: Space-separated dependency specifications (e.g., "scipy==1.7.3 numpy==1.21.6")
    
    Returns:
        List of dicts with 'package' and 'version' keys
    """
    if not dep_string or dep_string.strip() == "":
        return []
    
    deps = []
    for dep in dep_string.strip().split():
        if "==" in dep:
            package, version = dep.split("==")
            deps.append({"package": package, "version": version})
        else:
            deps.append({"package": dep, "version": None})
    
    return deps


def extract_version_info(dataset_path: str) -> Dict:
    """
    Extract all version information from the dataset.
    
    Args:
        dataset_path: Path to the dataset.jsonl file
    
    Returns:
        Dictionary containing all extracted version information
    """
    # Data structures to collect information
    python_versions: Set[str] = set()
    library_to_versions: Dict[str, Set[str]] = defaultdict(set)
    lib_version_to_deps: Dict[str, Set[str]] = defaultdict(set)
    python_lib_version_to_deps: Dict[str, Set[str]] = defaultdict(set)
    
    # Read and process the dataset
    with open(dataset_path, 'r') as f:
        for line_num, line in enumerate(f, 1):
            try:
                entry = json.loads(line.strip())
                
                # Extract python version
                python_ver = entry.get("python_version", "")
                if python_ver:
                    python_versions.add(python_ver)
                
                # Extract library and version
                library = entry.get("library", "")
                lib_version = entry.get("version", "")
                additional_deps = entry.get("additional_dependencies", "")
                
                # 1. Main library versions: library -> [versions]
                if library and lib_version:
                    library_to_versions[library].add(lib_version)
                
                # 2. Library version + additional dependencies: "library==version" -> [deps]
                if library and lib_version and additional_deps:
                    lib_key = f"{library}=={lib_version}"
                    lib_version_to_deps[lib_key].add(additional_deps)
                
                # 3. Full environment: "python_ver|library==version" -> [deps]
                if python_ver and library and lib_version:
                    env_key = f"{python_ver}|{library}=={lib_version}"
                    if additional_deps:
                        python_lib_version_to_deps[env_key].add(additional_deps)
                    else:
                        # Ensure key exists even with no deps
                        python_lib_version_to_deps[env_key].add("")
                        
            except json.JSONDecodeError as e:
                print(f"Warning: Failed to parse line {line_num}: {e}")
                continue
    
    # Convert sets to sorted lists for JSON serialization
    library_versions_dict = {
        lib: sorted(list(versions)) 
        for lib, versions in sorted(library_to_versions.items())
    }
    
    lib_with_deps_dict = {
        lib_ver: sorted([d for d in deps if d])  # Filter out empty strings
        for lib_ver, deps in sorted(lib_version_to_deps.items())
    }
    
    full_env_dict = {
        env: sorted([d for d in deps if d])  # Filter out empty strings
        for env, deps in sorted(python_lib_version_to_deps.items())
    }
    
    return {
        "python_versions": sorted(list(python_versions)),
        "library_versions": library_versions_dict,
        "library_version_with_dependencies": lib_with_deps_dict,
        "python_library_version_with_dependencies": full_env_dict,
        "statistics": {
            "total_python_versions": len(python_versions),
            "total_libraries": len(library_versions_dict),
            "total_library_version_combinations": sum(len(versions) for versions in library_versions_dict.values()),
            "total_lib_version_with_deps": len(lib_with_deps_dict),
            "total_full_environments": len(full_env_dict)
        }
    }


def main():
    """Main function to extract and save version information."""
    # Determine dataset path - check multiple possible locations
    script_dir = Path(__file__).parent
    
    # Try local dataset first
    dataset_path = script_dir / "dataset" / "dataset.jsonl"
    
    # If not found locally, try the GitChameleonBenchmark in the parent github directory
    if not dataset_path.exists():
        github_dir = Path(__file__).parent.parent.parent.parent / "GitChameleonBenchmark"
        dataset_path = github_dir / "dataset" / "dataset.jsonl"
    
    if not dataset_path.exists():
        print(f"Error: Dataset not found at {dataset_path}")
        print(f"Searched in:")
        print(f"  1. {script_dir / 'dataset' / 'dataset.jsonl'}")
        print(f"  2. {dataset_path}")
        return
    
    print(f"Extracting version information from {dataset_path}...")
    
    # Extract information
    version_info = extract_version_info(str(dataset_path))
    
    # Save to JSON file
    output_path = script_dir / "version_info.json"
    with open(output_path, 'w') as f:
        json.dump(version_info, f, indent=2)
    
    print(f"\nVersion information saved to {output_path}")
    
    # Print statistics
    print("\n" + "="*60)
    print("STATISTICS")
    print("="*60)
    stats = version_info["statistics"]
    print(f"Total Python versions: {stats['total_python_versions']}")
    print(f"Total libraries: {stats['total_libraries']}")
    print(f"Total library-version combinations: {stats['total_library_version_combinations']}")
    print(f"Total lib-version + deps combinations: {stats['total_lib_version_with_deps']}")
    print(f"Total full environments: {stats['total_full_environments']}")
    
    print("\n" + "="*60)
    print("PYTHON VERSIONS")
    print("="*60)
    for py_ver in version_info["python_versions"]:
        print(f"  - {py_ver}")
    
    print("\n" + "="*60)
    print("LIBRARY VERSIONS (first 5 libraries)")
    print("="*60)
    for i, (lib, versions) in enumerate(version_info["library_versions"].items()):
        if i >= 5:
            print(f"  ... and {len(version_info['library_versions']) - 5} more libraries")
            break
        print(f"  {lib}: {versions}")
    
    print("\nExtraction complete!")


if __name__ == "__main__":
    main()
