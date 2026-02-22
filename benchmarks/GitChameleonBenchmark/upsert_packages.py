#!/usr/bin/env python3
"""
Process library versions from GitChameleon dataset.

This script:
1. Reads library versions from version_info.json
2. For each selected library version:
    - Downloads a wheel without dependencies
    - Unpacks the wheel and statically analyzes source files
   - Uses com_extractor to extract code entities
   - Uploads entities to Neo4j using com_store
    - Cleans up temporary artifacts
   - Proceeds to the next version
"""

import json
import sys
import os
import logging
import argparse
from pathlib import Path
from typing import Dict, List, Optional
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'backend'))

from core.uploader import (
    init_stores,
    close_stores,
    check_version_exists,
    process_library_version,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


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


def main():
    """Main function."""
    # Setup argument parser
    parser = argparse.ArgumentParser(
        description="Process library versions from GitChameleon dataset and upload to Neo4j/Postgres",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --show-packages              # Show all available packages
  %(prog)s --library numpy              # Process all versions of numpy
  %(prog)s --library numpy --version 1.19.0  # Process specific version
  %(prog)s --all                        # Process all libraries and versions
  %(prog)s --library torch --keep-venv  # Keep virtual environment after processing
  %(prog)s --target postgres            # Upload to Postgres only
    %(prog)s --target postgres --purge-postgres  # Purge Postgres tables before processing
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
        help='Keep temporary wheel artifacts after processing (for debugging)'
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

    parser.add_argument(
        '--target',
        type=str,
        default='neo4j',
        help='Comma-separated list of targets: neo4j, postgres, or all (default: neo4j)'
    )

    parser.add_argument(
        '--postgres-url',
        type=str,
        default=None,
        help='Postgres connection URL (overrides env var)'
    )

    parser.add_argument(
        '--purge-postgres',
        action='store_true',
        help='Purge all COM tables in Postgres before processing starts'
    )
    
    args = parser.parse_args()
    
    # Determine paths
    script_dir = Path(__file__).parent
    deputy_root = script_dir.parent.parent
    backend_dir = deputy_root / "backend"
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

    # Processing Targets
    targets_arg = args.target.lower()
    if targets_arg == 'all':
        targets = ['neo4j', 'postgres']
    else:
        targets = [t.strip() for t in targets_arg.split(',')]
    
    # Config
    config = {
        'neo4j_username': os.getenv('NEO4J_USER', 'neo4j'),
        'neo4j_password': os.getenv('NEO4J_PASSWORD', ''),
        'neo4j_url': os.getenv('NEO4J_URI', 'bolt://localhost:7687'),
        'neo4j_database': os.getenv('NEO4J_DATABASE', 'neo4j'),
        'embed_nodes': os.getenv('EMBED_NODES', 'false').lower() == 'true',
        'postgres_url': args.postgres_url or os.getenv('SUPABASE_DB_URL'),
        'batch_size': args.batch_size
    }
    
    # Validate configs
    if 'neo4j' in targets and not config['neo4j_password']:
         logger.warning("NEO4J_PASSWORD not set. Neo4j might fail if authentication is required.")
    
    if 'postgres' in targets and not config['postgres_url']:
        logger.error("Postgres URL is required for postgres target. Use --postgres-url or set SUPABASE_DB_URL/POSTGRES_URL env var.")
        return 1

    if args.purge_postgres:
        if 'postgres' not in targets:
            logger.error("--purge-postgres requires postgres target. Use --target postgres or --target all.")
            return 1
        stores = init_stores(config, targets)
        if 'postgres' not in stores:
            logger.error("Postgres store is not initialized; cannot purge tables.")
            return 1
        logger.warning("Resetting Postgres schema (drop + recreate) before processing...")
        stores['postgres'].reset_schema()

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
    logger.info(f"Targets: {targets}")
    
    # Create working directory
    work_dir = script_dir / "venvs"
    work_dir.mkdir(exist_ok=True)
    
    # Process each version
    successful = 0
    failed = 0
    skipped = 0
    
    # Determine skip_existing behavior
    skip_existing = args.skip_existing and not args.force
    
    for i, lib_version in enumerate(versions_to_process, 1):
        library = lib_version['library']
        version = lib_version['version']
        additional_deps = lib_version.get('additional_dependencies', [])
        
        logger.info(f"\n{'='*60}")
        logger.info(f"Processing {i}/{len(versions_to_process)}: {library}=={version}")
        logger.info(f"{'='*60}")
        
        # Check if already exists before full processing
        if skip_existing and check_version_exists(library, version, config, targets):
            logger.info(f"⊙ Skipping {library}=={version} - already exists in target databases")
            skipped += 1
            successful += 1  # Count as successful since it's already in DB
            continue
        
        if process_library_version(
            library=library,
            version=version,
            additional_deps=additional_deps,
            work_dir=work_dir,
            config=config,
            targets=targets,
            keep_venv=args.keep_venv,
            use_conda=args.use_conda,
            use_available_python=args.use_available_python,
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
    
    # Close connections
    close_stores()
    
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
