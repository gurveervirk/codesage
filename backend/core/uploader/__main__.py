#!/usr/bin/env python3
import argparse
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dotenv import load_dotenv

from .stores import init_stores, close_stores, check_version_exists
from .pipeline import process_library_version

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s.%(msecs)03d - %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
    force=True,
)
logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Upload library versions to Neo4j/Postgres stores",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --library numpy --version 1.19.0
  %(prog)s --library numpy --version 1.19.0,1.20.0,1.21.0
  %(prog)s --packages numpy==1.19.0,torch==2.0.0
  %(prog)s --library requests --target postgres
  %(prog)s --library flask --version 2.3.0 --keep-venv
        """,
    )

    parser.add_argument(
        "--library",
        type=str,
        help="Library name to process",
    )

    parser.add_argument(
        "--version",
        type=str,
        help="Comma-separated version(s) to process (requires --library, e.g. 1.19.0,1.20.0)",
    )

    parser.add_argument(
        "--packages",
        type=str,
        help="Comma-separated list of lib==version pairs (e.g. numpy==1.19.0,torch==2.0.0)",
    )

    parser.add_argument(
        "--keep-venv",
        action="store_true",
        help="Keep temporary wheel artifacts after processing",
    )

    parser.add_argument(
        "--skip-existing",
        action="store_true",
        default=True,
        help="Skip versions already in the database (default: True)",
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help="Force processing even if version already exists",
    )

    parser.add_argument(
        "--use-conda",
        action="store_true",
        help="Use conda to create virtual environments",
    )

    parser.add_argument(
        "--use-available-python",
        action="store_true",
        help="Use any available Python version instead of requiring the specified version",
    )

    parser.add_argument(
        "--python-version",
        type=str,
        default="3.13",
        help="Python version to use for virtual environments (default: 3.13)",
    )

    parser.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help="Batch size for upserting entities and relations",
    )

    parser.add_argument(
        "--target",
        type=str,
        default="neo4j",
        help="Comma-separated list of targets: neo4j, postgres, or all (default: neo4j)",
    )

    parser.add_argument(
        "--postgres-url",
        type=str,
        default=None,
        help="Postgres connection URL (overrides env var)",
    )

    parser.add_argument(
        "--purge-postgres",
        action="store_true",
        help="Purge all COM tables in Postgres before processing",
    )

    parser.add_argument(
        "--work-dir",
        type=str,
        default=None,
        help="Working directory for venvs and artifacts (default: ./deputy_upload_work)",
    )

    args = parser.parse_args()

    backend_dir = Path(__file__).parent.parent.parent
    env_file = backend_dir / ".env"
    if env_file.exists():
        logger.info(f"Loading configuration from {env_file}")
        load_dotenv(env_file)
    else:
        logger.warning(f"No .env file found at {env_file}, using environment variables")

    if not args.library and not args.packages:
        parser.error("Must specify either --library or --packages")

    if args.library and args.packages:
        parser.error("Cannot specify both --library and --packages")

    if args.version and not args.library:
        parser.error("--version requires --library")

    targets_arg = args.target.lower()
    if targets_arg == "all":
        targets = ["neo4j", "postgres"]
    else:
        targets = [t.strip() for t in targets_arg.split(",")]

    config = {
        "neo4j_username": os.getenv("NEO4J_USER", "neo4j"),
        "neo4j_password": os.getenv("NEO4J_PASSWORD", ""),
        "neo4j_url": os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        "neo4j_database": os.getenv("NEO4J_DATABASE", "neo4j"),
        "embed_nodes": os.getenv("EMBED_NODES", "false").lower() == "true",
        "postgres_url": args.postgres_url or os.getenv("SUPABASE_DB_URL"),
        "batch_size": args.batch_size,
    }

    if "neo4j" in targets and not config["neo4j_password"]:
        logger.warning("NEO4J_PASSWORD not set. Neo4j might fail if authentication is required.")

    if "postgres" in targets and not config["postgres_url"]:
        logger.error(
            "Postgres URL is required for postgres target. Use --postgres-url or set SUPABASE_DB_URL env var."
        )
        return 1

    if args.purge_postgres:
        if "postgres" not in targets:
            logger.error("--purge-postgres requires postgres target.")
            return 1
        stores = init_stores(config, targets)
        if "postgres" not in stores:
            logger.error("Postgres store is not initialized; cannot purge tables.")
            return 1
        logger.warning("Resetting Postgres schema (drop + recreate) before processing...")
        stores["postgres"].reset_schema()

    if args.packages:
        versions_to_process = []
        for entry in args.packages.split(","):
            entry = entry.strip()
            if "==" in entry:
                lib, ver = entry.split("==", 1)
                versions_to_process.append({"library": lib.strip(), "version": ver.strip()})
            else:
                parser.error(f"Invalid package spec '{entry}'. Expected format: library==version")
    else:
        if args.version:
            versions = [v.strip() for v in args.version.split(",") if v.strip()]
            versions_to_process = [{"library": args.library, "version": v} for v in versions]
        else:
            parser.error("--library requires --version when not using --packages")

    work_dir = Path(args.work_dir) if args.work_dir else Path.cwd() / "deputy_upload_work"
    work_dir.mkdir(parents=True, exist_ok=True)

    skip_existing = args.skip_existing and not args.force

    successful = 0
    failed = 0
    skipped = 0

    logger.info(f"Will process {len(versions_to_process)} library version(s)")
    logger.info(f"Targets: {targets}")

    for i, item in enumerate(versions_to_process, 1):
        library = item["library"]
        version = item["version"]

        logger.info(f"\n{'='*60}")
        logger.info(f"Processing {i}/{len(versions_to_process)}: {library}=={version}")
        logger.info(f"{'='*60}")

        if skip_existing and check_version_exists(library, version, config, targets):
            logger.info(f"⊙ Skipping {library}=={version} - already exists in target databases")
            skipped += 1
            successful += 1
            continue

        if process_library_version(
            library=library,
            version=version,
            additional_deps=[],
            work_dir=work_dir,
            config=config,
            targets=targets,
            keep_venv=args.keep_venv,
            use_conda=args.use_conda,
            use_available_python=args.use_available_python,
            python_version=args.python_version,
        ):
            successful += 1
        else:
            failed += 1
            logger.error(f"✗ Failed to process {library}=={version}")

    logger.info(f"\n{'='*60}")
    logger.info("PROCESSING COMPLETE")
    logger.info(f"{'='*60}")
    logger.info(f"Successful: {successful}/{len(versions_to_process)}")
    if skipped > 0:
        logger.info(f"Skipped (already in DB): {skipped}/{len(versions_to_process)}")
    logger.info(f"Failed: {failed}/{len(versions_to_process)}")
    logger.info(f"{'='*60}")

    close_stores()

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
