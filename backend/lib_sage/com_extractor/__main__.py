"""
Command-line interface for COMExtractor.

Usage:
    python -m backend.lib_sage.com_extractor package <name> [--version VERSION]
    python -m backend.lib_sage.com_extractor module <name> [--version VERSION]
"""

import argparse
import logging
import sys

from . import process_package, process_module


def main():
    parser = argparse.ArgumentParser(
        description="Process Python packages or modules to extract entities and relationships."
    )
    parser.add_argument(
        "mode",
        choices=["package", "module"],
        help="Processing mode: 'package' to process a package (all top-level modules), 'module' to process a single module"
    )
    parser.add_argument(
        "name",
        help="Name of the package or module to process"
    )
    parser.add_argument(
        "--version",
        "-v",
        default=None,
        help="Version of the package/module (optional)"
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging level (default: INFO)"
    )
    parser.add_argument(
        "--no-external-parents",
        action="store_true",
        help="Disable processing of external parent classes (only for module mode)"
    )
    
    args = parser.parse_args()
    
    # Configure logging
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    try:
        if args.mode == "package":
            logging.info(f"Processing package: {args.name} (version: {args.version or 'latest'})")
            entities, relations, other_relations = process_package(args.name, args.version)
        else:  # module
            logging.info(f"Processing module: {args.name} (version: {args.version or 'latest'})")
            include_external = not args.no_external_parents
            entities, relations, other_relations = process_module(
                args.name, args.version, include_external_parents=include_external
            )
        
        # Print summary
        print(f"\n{'='*60}")
        print(f"Processing completed successfully!")
        print(f"{'='*60}")
        print(f"Mode: {args.mode}")
        print(f"Name: {args.name}")
        print(f"Version: {args.version or 'latest'}")
        print(f"\nResults:")
        print(f"  - Entities: {len(entities)}")
        print(f"  - Relations: {len(relations)}")
        print(f"  - INHERITS: {len(other_relations.get('INHERITS', []))}")
        print(f"  - EXPOSES: {len(other_relations.get('EXPOSES', []))}")
        print(f"  - PUBLISHES: {len(other_relations.get('PUBLISHES', []))}")
        print(f"{'='*60}\n")
        
        sys.exit(0)
        
    except Exception as e:
        logging.error(f"Error processing {args.mode} '{args.name}': {e}")
        import traceback
        logging.error(traceback.format_exc())
        print(f"\nError: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
