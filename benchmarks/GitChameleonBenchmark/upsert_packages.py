#!/usr/bin/env python3
"""
Process library versions from GitChameleon dataset.

This script:
1. Reads library versions from version_info.json
2. For each selected library version:
   - Creates an isolated virtual environment
   - Installs the specific library version
   - Uses com_extractor to extract code entities
   - Uploads entities to Neo4j using com_store
   - Cleans up the virtual environment
   - Proceeds to the next version
"""

import json
import subprocess
import sys
import os
import shutil
import logging
import argparse
from pathlib import Path
from typing import Dict, List, Optional
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'backend'))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

try:
    from lib_sage.com_store import COMStore as _COMStore
    COMStore = _COMStore
except ImportError:
    COMStore = None  # Placeholder if import fails
    _COMStore = None
    logger.warning("COMStore import failed, functionality will be limited. Error: ", exc_info=True)

# Global COMStore instance
_com_store = None


def init_com_store(neo4j_config: Dict, batch_size: Optional[int] = None):
    """Initialize or return the global COMStore instance."""
    global _com_store
    if _com_store is None:
        logger.info(f"Initializing COMStore connection to {neo4j_config.get('url')}")
        init_kwargs = {
            'username': neo4j_config.get('username', 'neo4j'),
            'password': neo4j_config.get('password', 'password'),
            'url': neo4j_config.get('url', 'bolt://localhost:7687'),
            'database': neo4j_config.get('database', 'neo4j'),
        }
        if batch_size is not None:
            init_kwargs['batch_size'] = batch_size
            logger.info(f"Initializing COMStore with custom batch_size: {batch_size}")
        _com_store = COMStore(**init_kwargs)
    return _com_store


def close_com_store():
    """Close the global COMStore connection."""
    global _com_store
    if _com_store is not None:
        logger.info("Closing COMStore connection")
        _com_store._driver.close()
        _com_store = None


def load_version_info(version_info_path: Path) -> Dict:
    """Load the version_info.json file."""
    if not version_info_path.exists():
        raise FileNotFoundError(f"version_info.json not found at {version_info_path}")
    
    with open(version_info_path, 'r') as f:
        return json.load(f)


def show_packages(library_versions: Dict[str, List[str]]) -> None:
    """
    Display all available packages with their version counts.
    
    Args:
        library_versions: Dict mapping library names to lists of versions
    """
    libraries = sorted(library_versions.keys())
    
    print("\n" + "="*60)
    print("Available Libraries:")
    print("="*60)
    for i, lib in enumerate(libraries, 1):
        versions = library_versions[lib]
        print(f"{i:3d}. {lib} ({len(versions)} version(s))")
    print("="*60)
    print(f"\nTotal: {len(libraries)} libraries")
    print("="*60 + "\n")


def get_library_versions(
    library_name: str, 
    library_versions_dict: Dict[str, List[str]],
    lib_with_deps_dict: Dict[str, List[str]]
) -> List[Dict[str, any]]:
    """
    Get all versions for a specific library with their dependencies.
    
    Args:
        library_name: Name of the library or "ALL"
        library_versions_dict: Dict mapping library -> [versions]
        lib_with_deps_dict: Dict mapping "library==version" -> [deps]
    
    Returns:
        List of dicts with 'library', 'version', 'dependencies' keys
    """
    result = []
    
    if library_name == "ALL":
        libs_to_process = library_versions_dict.keys()
    else:
        libs_to_process = [library_name]
    
    for lib in libs_to_process:
        for version in library_versions_dict.get(lib, []):
            lib_ver_key = f"{lib}=={version}"
            deps_list = lib_with_deps_dict.get(lib_ver_key, [])
            
            # Parse dependencies from string format "pkg1==ver1 pkg2==ver2"
            parsed_deps = []
            for dep_string in deps_list:
                if dep_string:
                    for dep in dep_string.split():
                        if "==" in dep:
                            pkg, ver = dep.split("==", 1)
                            parsed_deps.append({"package": pkg, "version": ver})
                        else:
                            parsed_deps.append({"package": dep, "version": None})
            
            result.append({
                "library": lib,
                "version": version,
                "additional_dependencies": parsed_deps
            })
    
    return result


def create_venv(venv_path: Path, use_conda: bool = False, use_available_python: bool = False, python_version: str = "3.13") -> bool:
    """
    Create a virtual environment using specified Python version.
    
    Args:
        venv_path: Path where the venv should be created
        use_conda: If True, try to use conda to create the environment
        use_available_python: If True, use any available Python version instead of requiring specified version
        python_version: Python version to use (default: 3.13)
    
    Returns:
        True if successful, False otherwise
    """
    try:
        # If conda is requested or available, try to use it
        if use_conda:
            try:
                # Check if conda is available
                conda_result = subprocess.run(
                    ["conda", "--version"],
                    capture_output=True,
                    text=True
                )
                if conda_result.returncode == 0:
                    logger.info(f"Using conda to create environment at {venv_path} with Python {python_version}")
                    subprocess.run(
                        ["conda", "create", "-p", str(venv_path), f"python={python_version}", "-y"],
                        check=True,
                        capture_output=True
                    )
                    logger.info(f"Conda environment created at {venv_path}")
                    return True
            except (subprocess.CalledProcessError, FileNotFoundError) as e:
                logger.warning(f"Conda environment creation failed, falling back to venv: {e}")
        
        # Try to find specified Python version executable (or any Python if use_available_python is True)
        major_minor = ".".join(python_version.split(".")[:2])  # e.g., "3.13" from "3.13.1"
        python_candidates = [f"python{major_minor}", "python3", "python"]
        python_exe = None
        found_version = None
        
        for candidate in python_candidates:
            try:
                result = subprocess.run(
                    [candidate, "--version"],
                    capture_output=True,
                    text=True,
                    check=True
                )
                version_output = result.stdout.strip()
                
                # If use_available_python is True, accept any Python version
                if use_available_python:
                    python_exe = candidate
                    found_version = version_output
                    logger.info(f"Found Python: {version_output}")
                    break
                elif f"Python {major_minor}" in version_output:
                    python_exe = candidate
                    found_version = version_output
                    logger.info(f"Found Python {major_minor}: {version_output}")
                    break
            except (subprocess.CalledProcessError, FileNotFoundError):
                continue
        
        if not python_exe:
            if use_available_python:
                logger.error("No Python executable found.")
            else:
                logger.error(f"Python {major_minor} not found. Please install Python {major_minor}, use --use-conda with --python-version, or use --use-available-python flag")
            logger.error("Tried: " + ", ".join(python_candidates))
            return False
        
        logger.info(f"Creating virtual environment at {venv_path} using {python_exe}")
        subprocess.run(
            [python_exe, "-m", "venv", str(venv_path)],
            check=True,
            capture_output=True
        )
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to create venv: {e.stderr.decode()}")
        return False


def get_venv_python(venv_path: Path) -> Path:
    """Get the path to the Python executable in the venv or conda env."""
    if sys.platform == "win32":
        # Try conda path first, then venv path
        conda_python = venv_path / "python.exe"
        venv_python = venv_path / "Scripts" / "python.exe"
        return conda_python if conda_python.exists() else venv_python
    else:
        # Try conda path first, then venv path
        conda_python = venv_path / "bin" / "python"
        venv_python = venv_path / "bin" / "python"
        return conda_python if conda_python.exists() else venv_python


def install_package(venv_path: Path, package_spec: str) -> bool:
    """
    Install a package in the virtual environment.
    
    Args:
        venv_path: Path to the virtual environment
        package_spec: Package specification (e.g., "torch==1.9.0")
    
    Returns:
        True if successful, False otherwise
    """
    python_exe = get_venv_python(venv_path)
    
    try:
        logger.info(f"Installing {package_spec}")
        cmd = [str(python_exe), "-m", "pip", "install", "--quiet", package_spec]
        # Include pydantic as it's required for com_extractor
        if "pydantic" not in package_spec.lower():
            cmd += ["pydantic"]
        subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            timeout=600  # 10 minute timeout for installation
        )
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to install {package_spec}: {e.stderr.decode()}")
        return False
    except subprocess.TimeoutExpired:
        logger.error(f"Installation of {package_spec} timed out")
        return False


def run_extraction_in_venv(
    venv_path: Path,
    library: str,
    version: str,
    codesage_root: Path
) -> Optional[tuple]:
    """
    Run the code extraction inside the virtual environment.
    
    Args:
        venv_path: Path to the virtual environment
        library: Library name
        version: Library version
        codesage_root: Path to CodeSage root directory
    
    Returns:
        Tuple of (entities, relations, other_relations) or None if failed
    """
    python_exe = get_venv_python(venv_path)
    
    # Create a temporary Python script to run inside the venv
    extraction_script = f"""
import sys
import os

# Add CodeSage backend to path
sys.path.insert(0, r"{codesage_root / 'backend'}")

try:
    from lib_sage.com_extractor import process_package
    
    # Process the package
    entities, relations, other_relations = process_package("{library}", version="{version}")
    
    # Save results to a temporary file
    import json
    import pickle
    
    results = {{
        'entities': entities,
        'relations': relations,
        'other_relations': other_relations
    }}
    
    # Serialize using pickle for complex objects
    with open('extraction_results.pkl', 'wb') as f:
        pickle.dump(results, f)
    
    print("EXTRACTION_SUCCESS")
    
except Exception as e:
    import traceback
    print(f"EXTRACTION_ERROR: {{str(e)}}", file=sys.stderr)
    traceback.print_exc(file=sys.stderr)
    sys.exit(1)
"""
    
    script_path = venv_path / "extract_code.py"
    results_path = venv_path / "extraction_results.pkl"
    
    try:
        # Write the extraction script
        with open(script_path, 'w') as f:
            f.write(extraction_script)
        
        # Run the script
        logger.info(f"Extracting entities from {library}=={version}")
        result = subprocess.run(
            [str(python_exe), str(script_path)],
            cwd=str(venv_path),
            capture_output=True,
            timeout=1800,  # 30 minute timeout
            text=True
        )
        
        if result.returncode != 0:
            logger.error(f"Extraction failed: {result.stderr}")
            return None
        
        if "EXTRACTION_SUCCESS" not in result.stdout:
            logger.error(f"Extraction did not complete successfully")
            return None
        
        # Load the results
        import pickle
        with open(results_path, 'rb') as f:
            results = pickle.load(f)
        
        logger.info(f"Extracted {len(results['entities'])} entities and {len(results['relations'])} relations")
        return (results['entities'], results['relations'], results['other_relations'])
        
    except subprocess.TimeoutExpired:
        logger.error(f"Extraction timed out for {library}=={version}")
        return None
    except Exception as e:
        logger.error(f"Error during extraction: {e}")
        return None
    finally:
        # Cleanup temporary files
        if script_path.exists():
            script_path.unlink()
        if results_path.exists():
            results_path.unlink()


def check_version_exists(
    library: str,
    version: str,
    neo4j_config: Dict
) -> bool:
    """
    Check if a library version already exists in Neo4j.
    
    Args:
        library: Library name
        version: Library version
        neo4j_config: Neo4j connection configuration
    
    Returns:
        True if the version exists, False otherwise
    """
    try:
        # Use global COMStore instance
        store = init_com_store(neo4j_config, batch_size=None)
        
        # Sanitize version label
        version_label = f"version_{version.replace('.', '_').replace(':', '_').replace('-', '_')}"
        
        # Query to check if ROOT_MODULE with this library name and version exists
        check_query = """
        MATCH (root:ROOT_MODULE {name: $library_name})
        WHERE $version_label IN labels(root)
        RETURN count(root) > 0 AS exists
        """
        
        result = store.structured_query(check_query, {
            "library_name": library,
            "version_label": version_label
        })
        
        exists = result[0]['exists'] if result else False
        
        return exists
        
    except Exception as e:
        logger.error(f"Error checking if {library}=={version} exists: {e}")
        import traceback
        traceback.print_exc()
        return False


def upload_to_neo4j(
    entities: List,
    relations: List,
    other_relations: Dict,
    library: str,
    version: str,
    neo4j_config: Dict,
    batch_size: Optional[int] = None
) -> bool:
    """
    Upload extracted entities to Neo4j.
    
    Args:
        entities: List of Entity objects
        relations: List of Relationship objects
        other_relations: Dict of other relationship types
        library: Library name
        version: Library version
        neo4j_config: Neo4j connection configuration
        batch_size: Optional batch size for upserting entities and relations
    
    Returns:
        True if successful, False otherwise
    """
    try:
        # Use global COMStore instance
        store = init_com_store(neo4j_config, batch_size=batch_size)
        
        # Upload to Neo4j
        logger.info(f"Uploading {len(entities)} entities to Neo4j for {library}=={version}")
        store.upsert_to_neo4j(
            module_name=library,
            entities=entities,
            relations=relations,
            other_relations=other_relations,
        )
        
        logger.info(f"Successfully uploaded {library}=={version} to Neo4j")
        return True
        
    except Exception as e:
        logger.error(f"Failed to upload to Neo4j: {e}")
        import traceback
        traceback.print_exc()
        return False


def process_library_version(
    library: str,
    version: str,
    additional_deps: List[Dict],
    work_dir: Path,
    codesage_root: Path,
    neo4j_config: Dict,
    keep_venv: bool = False,
    use_conda: bool = False,
    use_available_python: bool = False,
    batch_size: Optional[int] = None,
    python_version: str = "3.13"
) -> bool:
    """
    Process a single library version.
    
    Args:
        library: Library name
        version: Library version
        additional_deps: List of additional dependencies
        work_dir: Working directory for temporary files
        codesage_root: Path to CodeSage root
        neo4j_config: Neo4j configuration
        keep_venv: Whether to keep the venv after processing
        use_conda: Whether to use conda for environment creation
        use_available_python: Whether to use any available Python version instead of requiring specified version
        batch_size: Optional batch size for upserting entities and relations
        python_version: Python version to use (default: 3.13)
    
    Returns:
        True if successful, False otherwise
    """
    venv_path = work_dir / f"venv_{library}_{version.replace('.', '_')}"
    
    try:
        # Step 1: Create virtual environment
        if not create_venv(venv_path, use_conda=use_conda, use_available_python=use_available_python, python_version=python_version):
            return False
        
        # Step 2: Install the library
        package_spec = f"{library}=={version}"
        if not install_package(venv_path, package_spec):
            return False
        
        # Step 3: Install additional dependencies
        for dep in additional_deps:
            dep_package = dep['package']
            dep_version = dep.get('version')
            if dep_version:
                dep_spec = f"{dep_package}=={dep_version}"
            else:
                dep_spec = dep_package
            
            if not install_package(venv_path, dep_spec):
                logger.warning(f"Failed to install dependency {dep_spec}, continuing anyway")
        
        # Step 4: Extract code entities
        extraction_result = run_extraction_in_venv(venv_path, library, version, codesage_root)
        if extraction_result is None:
            return False
        
        entities, relations, other_relations = extraction_result
        
        # Step 5: Upload to Neo4j
        if not upload_to_neo4j(entities, relations, other_relations, library, version, neo4j_config, batch_size=batch_size):
            return False
        
        logger.info(f"✓ Successfully processed {library}=={version}")
        return True
        
    except Exception as e:
        logger.error(f"Error processing {library}=={version}: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    finally:
        # Step 6: Cleanup virtual environment
        if not keep_venv and venv_path.exists():
            logger.info(f"Cleaning up venv at {venv_path}")
            try:
                shutil.rmtree(venv_path)
            except Exception as e:
                logger.warning(f"Failed to remove venv: {e}")


def main():
    """Main function."""
    # Setup argument parser
    parser = argparse.ArgumentParser(
        description="Process library versions from GitChameleon dataset and upload to Neo4j",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --show-packages              # Show all available packages
  %(prog)s --library numpy              # Process all versions of numpy
  %(prog)s --library numpy --version 1.19.0  # Process specific version
  %(prog)s --all                        # Process all libraries and versions
  %(prog)s --library torch --keep-venv  # Keep virtual environment after processing
  %(prog)s --library numpy --force      # Force re-processing even if already in DB
        """
    )
    
    parser.add_argument(
        '--show-packages',
        action='store_true',
        help='Display all available packages and exit'
    )
    
    parser.add_argument(
        '--library',
        type=str,
        help='Library name to process (e.g., numpy, torch)'
    )
    
    parser.add_argument(
        '--version',
        type=str,
        help='Specific version to process (requires --library)'
    )
    
    parser.add_argument(
        '--all',
        action='store_true',
        help='Process all libraries and versions'
    )
    
    parser.add_argument(
        '--keep-venv',
        action='store_true',
        help='Keep virtual environments after processing (for debugging)'
    )
    
    parser.add_argument(
        '--skip-existing',
        action='store_true',
        default=True,
        help='Skip library versions that already exist in the database (default: True)'
    )
    
    parser.add_argument(
        '--force',
        action='store_true',
        help='Force processing even if version exists (overrides --skip-existing)'
    )
    
    parser.add_argument(
        '--use-conda',
        action='store_true',
        help='Use conda to create virtual environments instead of venv'
    )
    
    parser.add_argument(
        '--use-available-python',
        action='store_true',
        help='Use any available Python version instead of requiring the specified version'
    )
    
    parser.add_argument(
        '--python-version',
        type=str,
        default='3.13',
        help='Python version to use for virtual environments (default: 3.13)'
    )
    
    parser.add_argument(
        '--batch-size',
        type=int,
        default=None,
        help='Batch size for upserting entities and relations (default: 1000 if not specified)'
    )
    
    args = parser.parse_args()
    
    # Determine paths
    script_dir = Path(__file__).parent
    codesage_root = script_dir.parent.parent
    backend_dir = codesage_root / "backend"
    version_info_path = script_dir / "version_info.json"
    
    # Load environment variables from backend/.env
    env_file = backend_dir / ".env"
    if env_file.exists():
        logger.info(f"Loading configuration from {env_file}")
        load_dotenv(env_file)
    else:
        logger.warning(f"No .env file found at {env_file}, using defaults/environment variables")
    
    # Load version information
    try:
        version_info = load_version_info(version_info_path)
    except FileNotFoundError as e:
        logger.error(str(e))
        logger.info("Please run extract_versions.py first to generate version_info.json")
        return 1
    
    library_versions_dict = version_info.get('library_versions', {})
    lib_with_deps_dict = version_info.get('library_version_with_dependencies', {})
    
    if not library_versions_dict:
        logger.error("No library versions found in version_info.json")
        logger.info("The version_info.json file may be empty or have an incorrect structure")
        return 1
    
    # Handle --show-packages
    if args.show_packages:
        show_packages(library_versions_dict)
        return 0
    
    # Validate arguments
    if args.version and not args.library:
        parser.error("--version requires --library to be specified")
    
    if not args.library and not args.all:
        parser.error("Must specify either --library, --all, or --show-packages")
    
    if args.library and args.all:
        parser.error("Cannot specify both --library and --all")
    
    # Validate library exists
    if args.library and args.library not in library_versions_dict:
        logger.error(f"Library '{args.library}' not found in version_info.json")
        logger.info(f"Use --show-packages to see available libraries")
        return 1
    
    # Validate version exists
    if args.version:
        available_versions = library_versions_dict[args.library]
        if args.version not in available_versions:
            logger.error(f"Version '{args.version}' not found for library '{args.library}'")
            logger.info(f"Available versions: {', '.join(available_versions)}")
            return 1
    
    # Determine what to process
    if args.all:
        selected_library = "ALL"
        logger.info(f"Processing ALL libraries ({len(library_versions_dict)} libraries)")
    else:
        selected_library = args.library
        if args.version:
            logger.info(f"Processing {selected_library}=={args.version}")
        else:
            version_count = len(library_versions_dict[selected_library])
            logger.info(f"Processing all versions of {selected_library} ({version_count} versions)")
    
    # Get versions to process
    if args.library and args.version:
        # Process single specific version
        lib_ver_key = f"{args.library}=={args.version}"
        deps_list = lib_with_deps_dict.get(lib_ver_key, [])
        
        parsed_deps = []
        for dep_string in deps_list:
            if dep_string:
                for dep in dep_string.split():
                    if "==" in dep:
                        pkg, ver = dep.split("==", 1)
                        parsed_deps.append({"package": pkg, "version": ver})
                    else:
                        parsed_deps.append({"package": dep, "version": None})
        
        versions_to_process = [{
            "library": args.library,
            "version": args.version,
            "additional_dependencies": parsed_deps
        }]
    else:
        versions_to_process = get_library_versions(selected_library, library_versions_dict, lib_with_deps_dict)
    
    logger.info(f"Will process {len(versions_to_process)} library version(s)")
    
    # Get Neo4j configuration from .env file (loaded above) or environment variables
    neo4j_config = {
        'username': os.getenv('NEO4J_USER', 'neo4j'),
        'password': os.getenv('NEO4J_PASSWORD', ''),
        'url': os.getenv('NEO4J_URI', 'bolt://localhost:7687'),
        'database': os.getenv('NEO4J_DATABASE', 'neo4j'),
        'embed_nodes': os.getenv('EMBED_NODES', 'false').lower() == 'true'
    }
    
    # Validate Neo4j configuration
    if not neo4j_config['password']:
        logger.error("NEO4J_PASSWORD is not set. Please configure it in backend/.env or as an environment variable.")
        return 1
    
    logger.info(f"Neo4j URL: {neo4j_config['url']}")
    logger.info(f"Neo4j User: {neo4j_config['username']}")
    logger.info(f"Neo4j Database: {neo4j_config['database']}")
    logger.info(f"Embed nodes: {neo4j_config['embed_nodes']}")
    if args.batch_size:
        logger.info(f"Batch size: {args.batch_size}")
    
    # Create working directory
    work_dir = script_dir / "venvs"
    work_dir.mkdir(exist_ok=True)
    
    # Process each version
    successful = 0
    failed = 0
    skipped = 0
    
    # Determine skip_existing behavior
    skip_existing = args.skip_existing and not args.force
    
    if skip_existing:
        logger.info("Will skip versions that already exist in the database")
    else:
        logger.info("Will process all versions, even if they already exist")
    
    for i, lib_version in enumerate(versions_to_process, 1):
        library = lib_version['library']
        version = lib_version['version']
        additional_deps = lib_version.get('additional_dependencies', [])
        
        logger.info(f"\n{'='*60}")
        logger.info(f"Processing {i}/{len(versions_to_process)}: {library}=={version}")
        logger.info(f"{'='*60}")
        
        # Check if already exists before full processing
        if skip_existing and check_version_exists(library, version, neo4j_config):
            logger.info(f"⊙ Skipping {library}=={version} - already exists in database")
            skipped += 1
            successful += 1  # Count as successful since it's already in DB
            continue
        
        if process_library_version(
            library=library,
            version=version,
            additional_deps=additional_deps,
            work_dir=work_dir,
            codesage_root=codesage_root,
            neo4j_config=neo4j_config,
            keep_venv=args.keep_venv,
            use_conda=args.use_conda,
            use_available_python=args.use_available_python,
            batch_size=args.batch_size,
            python_version=args.python_version
        ):
            successful += 1
        else:
            failed += 1
            logger.error(f"✗ Failed to process {library}=={version}")
    
    # Final summary
    logger.info(f"\n{'='*60}")
    logger.info(f"PROCESSING COMPLETE")
    logger.info(f"{'='*60}")
    logger.info(f"Successful: {successful}/{len(versions_to_process)}")
    if skipped > 0:
        logger.info(f"Skipped (already in DB): {skipped}/{len(versions_to_process)}")
    logger.info(f"Failed: {failed}/{len(versions_to_process)}")
    logger.info(f"{'='*60}")
    
    # Close the global COMStore connection
    close_com_store()
    
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
