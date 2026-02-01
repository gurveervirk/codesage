"""
Command-line interface for COMExtractor.

Usage:
    python -m backend.core.com_extractor package <name> [--version VERSION]
    python -m backend.core.com_extractor module <name> [--version VERSION]
"""

import argparse
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

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
    parser.add_argument(
        "--use-uv",
        action="store_true",
        help="Use uv for package installation instead of pip"
    )
    parser.add_argument(
        "--use-conda",
        action="store_true",
        help="Use conda for package installation instead of pip"
    )
    parser.add_argument(
        "--output",
        "-o",
        default=None,
        help="Output JSON file path to save results (default: <name>_extraction.json in current directory)"
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory to save output file (default: current working directory)"
    )
    parser.add_argument(
        "--log-file",
        default=None,
        help="Log file path to save logs (default: <name>_extraction.log in current directory if --log-dir specified)"
    )
    parser.add_argument(
        "--log-dir",
        default=None,
        help="Directory to save log file (default: no log file created unless --log-file specified)"
    )
    parser.add_argument(
        "--log-file-level",
        default="DEBUG",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Minimum logging level for log file (default: DEBUG)"
    )
    parser.add_argument(
        "--isolated-venv",
        action="store_true",
        help="Create and use an isolated virtual environment in CWD named <package>_<version>_venv"
    )
    
    args = parser.parse_args()
    
    # Determine install method
    if args.use_uv and args.use_conda:
        print("Error: Cannot specify both --use-uv and --use-conda", file=sys.stderr)
        sys.exit(1)
    
    install_method = "uv" if args.use_uv else "conda" if args.use_conda else "pip"
    
    # Handle isolated venv if requested
    original_executable = sys.executable
    venv_python = None
    if args.isolated_venv:
        # Create venv name from package name and version
        version_str = args.version if args.version else "latest"
        venv_name = f"{args.name.replace('.', '_')}_{version_str}_venv"
        venv_path = Path.cwd() / venv_name
        print(f"Creating isolated virtual environment: {venv_name}", file=sys.stderr)
        
        try:
            # Create venv based on method
            required_packages = ["pydantic", "packaging", "setuptools", "requests"]
            if install_method == "uv":
                # Create venv using uv
                subprocess.run(["uv", "venv", str(venv_path)], check=True, capture_output=True)
                # Install pydantic and packaging using uv pip
                subprocess.run(["uv", "pip", "install", "--python", str(venv_path / "bin" / "python")] + required_packages, check=True, capture_output=True)
                venv_python = venv_path / "bin" / "python"
            elif install_method == "conda":
                # Create conda environment
                subprocess.run(["conda", "create", "-y", "-p", str(venv_path), "python"] + required_packages, check=True, capture_output=True)
                venv_python = venv_path / "bin" / "python"
            else:  # pip
                # Create standard venv
                import venv
                venv.create(venv_path, with_pip=True)
                # Install pydantic and packaging using the venv's pip
                subprocess.run([str(venv_path / "bin" / "python"), "-m", "pip", "install"] + required_packages, check=True, capture_output=True)
                venv_python = venv_path / "bin" / "python"
            
            if not venv_python.exists():
                raise FileNotFoundError(f"Python executable not found at {venv_python}")
            
            print(f"Virtual environment created at: {venv_path}", file=sys.stderr)
            print(f"Using Python: {venv_python}", file=sys.stderr)
            
            # Re-execute this script with the venv Python
            # Build the command with all the original arguments except --isolated-venv
            new_args = [str(venv_python), "-m", "backend.core.com_extractor"]
            for arg in sys.argv[1:]:
                if arg != "--isolated-venv":
                    new_args.append(arg)
            
            # Execute in the new venv
            result = subprocess.run(new_args, env={**os.environ, "VIRTUAL_ENV": str(venv_path)})
            sys.exit(result.returncode)
            
        except subprocess.CalledProcessError as e:
            print(f"Error creating virtual environment: {e}", file=sys.stderr)
            if e.output:
                print(e.output.decode(), file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            print(f"Error setting up isolated environment: {e}", file=sys.stderr)
            sys.exit(1)
    
    # Configure logging
    log_handlers = []
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, args.log_level))
    console_formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    console_handler.setFormatter(console_formatter)
    log_handlers.append(console_handler)
    
    # File handler (if requested)
    if args.log_file or args.log_dir:
        # Determine log file path
        if args.log_file:
            log_path = Path(args.log_file)
            if not log_path.is_absolute() and args.log_dir:
                log_path = Path(args.log_dir) / log_path
        else:
            # Generate default filename
            log_filename = f"{args.name.replace('.', '_')}_extraction.log"
            if args.log_dir:
                log_path = Path(args.log_dir) / log_filename
            else:
                log_path = Path.cwd() / log_filename
        
        # Ensure parent directory exists
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Create file handler
        try:
            file_handler = logging.FileHandler(log_path, mode='w', encoding='utf-8')
            file_handler.setLevel(getattr(logging, args.log_file_level))
            file_formatter = logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s"
            )
            file_handler.setFormatter(file_formatter)
            log_handlers.append(file_handler)
            print(f"Logging to file: {log_path.absolute()}", file=sys.stderr)
        except Exception as e:
            print(f"Warning: Failed to create log file at {log_path}: {e}", file=sys.stderr)
    
    # Configure root logger
    logging.basicConfig(
        level=logging.DEBUG,  # Set to DEBUG to capture all, handlers will filter
        handlers=log_handlers,
        force=True
    )
    
    try:
        if args.mode == "package":
            logging.info(f"Processing package: {args.name} (version: {args.version or 'latest'}) using {install_method}")
            entities, relations, other_relations = process_package(args.name, args.version, install_method=install_method)
        else:  # module
            logging.info(f"Processing module: {args.name} (version: {args.version or 'latest'})")
            include_external = not args.no_external_parents
            entities, relations, other_relations = process_module(
                args.name, args.version, include_external_parents=include_external
            )
        
        # Categorize entities and relations for final summary
        if args.mode == "package":
            # For package mode, we need to determine the base module name(s)
            from backend.core.com_extractor.core import get_top_level_modules_for_package
            top_level_modules = get_top_level_modules_for_package(args.name)
            
            # Categorize as internal if belongs to any top-level module
            internal_entities = [e for e in entities if any(e.name.startswith(mod) for mod in top_level_modules)]
            external_entities = [e for e in entities if e not in internal_entities]
            
            internal_relations = [r for r in relations if any(r.from_entity.name.startswith(mod) and r.to_entity.name.startswith(mod) for mod in top_level_modules)]
            external_relations = [r for r in relations if r not in internal_relations]
            
            # Log per-root-module breakdown
            print(f"\n{'='*60}")
            print(f"Per Top-Level Module Breakdown:")
            print(f"{'='*60}")
            for mod in sorted(top_level_modules):
                mod_entities = [e for e in entities if e.name.startswith(mod)]
                mod_internal_entities = [e for e in mod_entities if e.name.startswith(mod)]
                mod_internal_relations = [r for r in relations if r.from_entity.name.startswith(mod) and r.to_entity.name.startswith(mod)]
                print(f"  {mod}:")
                print(f"    - Entities: {len(mod_internal_entities)}")
                print(f"    - Relations: {len(mod_internal_relations)}")
            print(f"{'='*60}")
        else:
            # For module mode, use the module name as base
            internal_entities = [e for e in entities if e.name.startswith(args.name)]
            external_entities = [e for e in entities if e not in internal_entities]
            
            internal_relations = [r for r in relations if r.from_entity.name.startswith(args.name) and r.to_entity.name.startswith(args.name)]
            external_relations = [r for r in relations if r not in internal_relations]
        
        # Print summary
        print(f"\n{'='*60}")
        print(f"Processing completed successfully!")
        print(f"{'='*60}")
        print(f"Mode: {args.mode}")
        print(f"Name: {args.name}")
        print(f"Version: {args.version or 'latest'}")
        print(f"\nResults:")
        print(f"  - Total Entities: {len(entities)}")
        print(f"    • Internal: {len(internal_entities)}")
        print(f"    • External: {len(external_entities)}")
        print(f"  - Total Relations: {len(relations)}")
        print(f"    • Internal: {len(internal_relations)}")
        print(f"    • External: {len(external_relations)}")
        print(f"  - INHERITS: {len(other_relations.get('INHERITS', []))}")
        print(f"  - EXPOSES: {len(other_relations.get('EXPOSES', []))}")
        print(f"  - PUBLISHES: {len(other_relations.get('PUBLISHES', []))}")
        print(f"{'='*60}\n")
        
        # Save to JSON if requested
        if args.output or args.output_dir:
            # Determine output path
            if args.output:
                # Use provided output path
                output_path = Path(args.output)
                if not output_path.is_absolute() and args.output_dir:
                    # Relative path with output_dir specified
                    output_path = Path(args.output_dir) / output_path
            else:
                # Generate default filename
                filename = f"{args.name.replace('.', '_')}_extraction.json"
                if args.output_dir:
                    output_path = Path(args.output_dir) / filename
                else:
                    output_path = Path.cwd() / filename
            
            # Ensure parent directory exists
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Convert entities and relationships to serializable format
            entities_data = [
                {
                    "name": e.name,
                    "labels": e.labels,
                    "properties": e.properties
                }
                for e in entities
            ]
            
            relations_data = [
                {
                    "from": r.from_entity.name,
                    "to": r.to_entity.name,
                    "type": r.label,
                    "properties": r.properties
                }
                for r in relations
            ]
            
            # Convert other_relations tuples to serializable format
            other_relations_data = {}
            for rel_type, rel_list in other_relations.items():
                other_relations_data[rel_type] = [
                    {
                        "from": item[0] if isinstance(item, tuple) else str(item),
                        "to": {
                            "name": item[1].name,
                            "version": item[1].version
                        } if isinstance(item, tuple) and hasattr(item[1], 'name') else str(item[1]) if isinstance(item, tuple) else str(item)
                    }
                    for item in rel_list
                ]
            
            output_data = {
                "metadata": {
                    "mode": args.mode,
                    "name": args.name,
                    "version": args.version or "latest",
                    "install_method": install_method if args.mode == "package" else None,
                    "include_external_parents": not args.no_external_parents if args.mode == "module" else None
                },
                "entities": entities_data,
                "relations": relations_data,
                "other_relations": other_relations_data,
                "summary": {
                    "total_entities": len(entities),
                    "total_relations": len(relations),
                    "inherits_count": len(other_relations.get('INHERITS', [])),
                    "exposes_count": len(other_relations.get('EXPOSES', [])),
                    "publishes_count": len(other_relations.get('PUBLISHES', []))
                }
            }
            
            # Write to file
            try:
                with open(output_path, 'w', encoding='utf-8') as f:
                    json.dump(output_data, f, indent=2, ensure_ascii=False)
                logging.info(f"Results saved to: {output_path.absolute()}")
                print(f"Results saved to: {output_path.absolute()}")
            except Exception as e:
                logging.error(f"Failed to save results to {output_path}: {e}")
                print(f"Warning: Failed to save results to {output_path}: {e}", file=sys.stderr)
        
        sys.exit(0)
        
    except Exception as e:
        logging.error(f"Error processing {args.mode} '{args.name}': {e}")
        import traceback
        logging.error(traceback.format_exc())
        print(f"\nError: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
