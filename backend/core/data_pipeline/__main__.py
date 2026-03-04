#!/usr/bin/env python3
import argparse
import logging
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

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


def _load_env():
    backend_dir = Path(__file__).parent.parent.parent
    env_file = backend_dir / ".env"
    if env_file.exists():
        logger.info(f"Loading configuration from {env_file}")
        load_dotenv(env_file)
    else:
        logger.warning(f"No .env file found at {env_file}, using environment variables")


def _build_config(postgres_url=None, batch_size=None):
    return {
        "neo4j_username": os.getenv("NEO4J_USER", "neo4j"),
        "neo4j_password": os.getenv("NEO4J_PASSWORD", ""),
        "neo4j_url": os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        "neo4j_database": os.getenv("NEO4J_DATABASE", "neo4j"),
        "embed_nodes": os.getenv("EMBED_NODES", "false").lower() == "true",
        "postgres_url": postgres_url or os.getenv("SUPABASE_DB_URL"),
        "batch_size": batch_size,
    }


def _resolve_targets(target_arg: str):
    if target_arg.lower() == "all":
        return ["neo4j", "postgres"]
    return [t.strip() for t in target_arg.split(",")]


def cmd_dump(args) -> int:
    _load_env()
    pg_url = args.postgres_url or os.getenv("SUPABASE_DB_URL")
    if not pg_url:
        logger.error("Postgres URL is required. Use --postgres-url or set SUPABASE_DB_URL.")
        return 1

    if args.dump_path:
        dump_path = Path(args.dump_path)
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dump_dir = Path(args.work_dir) if args.work_dir else Path.cwd() / "deputy_work"
        dump_dir.mkdir(parents=True, exist_ok=True)
        dump_path = dump_dir / f"postgres_dump_{timestamp}.sql"

    logger.info(f"Dumping Postgres data+schema to {dump_path} ...")
    try:
        parsed = urlparse(pg_url)
        env = os.environ.copy()
        if parsed.password:
            env["PGPASSWORD"] = parsed.password
        cmd = ["pg_dump", "--no-password", "--format=plain", f"--file={dump_path}"]
        if parsed.hostname:
            cmd += ["--host", parsed.hostname]
        if parsed.port:
            cmd += ["--port", str(parsed.port)]
        if parsed.username:
            cmd += ["--username", parsed.username]
        db_name = parsed.path.lstrip("/") if parsed.path else None
        if db_name:
            cmd.append(db_name)
        result = subprocess.run(cmd, env=env, capture_output=True, text=True)
        if result.returncode != 0:
            logger.error(f"pg_dump failed: {result.stderr.strip()}")
            return 1
        logger.info(f"Dump written to {dump_path}")
        return 0
    except FileNotFoundError:
        logger.error("pg_dump not found. Ensure PostgreSQL client tools are installed and on PATH.")
        return 1


def cmd_purge(args) -> int:
    _load_env()
    config = _build_config(postgres_url=args.postgres_url)
    if not config["postgres_url"]:
        logger.error("Postgres URL is required. Use --postgres-url or set SUPABASE_DB_URL.")
        return 1

    stores = init_stores(config, ["postgres"])
    if "postgres" not in stores:
        logger.error("Postgres store is not initialized; cannot purge tables.")
        return 1
    logger.warning("Resetting Postgres schema (drop + recreate)...")
    stores["postgres"].reset_schema()
    logger.info("Postgres schema reset complete.")
    return 0


def cmd_upload(args) -> int:
    _load_env()

    targets = _resolve_targets(args.target)
    config = _build_config(postgres_url=args.postgres_url, batch_size=args.batch_size)

    if "neo4j" in targets and not config["neo4j_password"]:
        logger.warning("NEO4J_PASSWORD not set. Neo4j might fail if authentication is required.")

    if "postgres" in targets and not config["postgres_url"]:
        logger.error("Postgres URL is required for postgres target. Use --postgres-url or set SUPABASE_DB_URL.")
        return 1

    if args.packages:
        versions_to_process = []
        for entry in args.packages.split(","):
            entry = entry.strip()
            if "==" in entry:
                lib, ver = entry.split("==", 1)
                versions_to_process.append({"library": lib.strip(), "version": ver.strip()})
            else:
                logger.error(f"Invalid package spec '{entry}'. Expected format: library==version")
                return 1
    else:
        if not args.version:
            logger.error("--library requires --version when not using --packages")
            return 1
        versions = [v.strip() for v in args.version.split(",") if v.strip()]
        versions_to_process = [{"library": args.library, "version": v} for v in versions]

    work_dir = Path(args.work_dir) if args.work_dir else Path.cwd() / "deputy_work"
    work_dir.mkdir(parents=True, exist_ok=True)

    skip_existing = not args.force

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


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Deputy data pipeline: upload, dump, and purge library store data",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    dump_parser = subparsers.add_parser(
        "dump",
        help="Dump Postgres data+schema to a SQL file",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --postgres-url postgresql://user:pass@host/db
  %(prog)s --dump-path /tmp/backup.sql
        """,
    )
    dump_parser.add_argument("--postgres-url", type=str, default=None, help="Postgres connection URL (overrides env var)")
    dump_parser.add_argument("--dump-path", type=str, default=None, help="Output path for the SQL dump file")
    dump_parser.add_argument("--work-dir", type=str, default=None, help="Directory for dump file if --dump-path not set (default: ./deputy_work)")

    purge_parser = subparsers.add_parser(
        "purge",
        help="Drop and recreate all COM tables in Postgres",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --postgres-url postgresql://user:pass@host/db
        """,
    )
    purge_parser.add_argument("--postgres-url", type=str, default=None, help="Postgres connection URL (overrides env var)")

    upload_parser = subparsers.add_parser(
        "upload",
        help="Extract and upload library versions to Neo4j/Postgres stores",
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
    upload_parser.add_argument("--library", type=str, help="Library name to process")
    upload_parser.add_argument("--version", type=str, help="Comma-separated version(s) to process (requires --library)")
    upload_parser.add_argument("--packages", type=str, help="Comma-separated lib==version pairs (e.g. numpy==1.19.0,torch==2.0.0)")
    upload_parser.add_argument("--keep-venv", action="store_true", help="Keep temporary wheel artifacts after processing")
    upload_parser.add_argument("--force", action="store_true", help="Force processing even if version already exists")
    upload_parser.add_argument("--use-conda", action="store_true", help="Use conda to create virtual environments")
    upload_parser.add_argument("--use-available-python", action="store_true", help="Use any available Python version")
    upload_parser.add_argument("--python-version", type=str, default="3.13", help="Python version for virtual environments (default: 3.13)")
    upload_parser.add_argument("--batch-size", type=int, default=None, help="Batch size for upserting entities and relations")
    upload_parser.add_argument("--target", type=str, default="postgres", help="Comma-separated targets: neo4j, postgres, or all (default: neo4j)")
    upload_parser.add_argument("--postgres-url", type=str, default=None, help="Postgres connection URL (overrides env var)")
    upload_parser.add_argument("--work-dir", type=str, default=None, help="Working directory for venvs and artifacts (default: ./deputy_work)")

    args = parser.parse_args()

    if args.command == "dump":
        return cmd_dump(args)
    if args.command == "purge":
        return cmd_purge(args)
    if args.command == "upload":
        if not args.library and not args.packages:
            upload_parser.error("Must specify either --library or --packages")
        if args.library and args.packages:
            upload_parser.error("Cannot specify both --library and --packages")
        if args.version and not args.library:
            upload_parser.error("--version requires --library")
        return cmd_upload(args)

    return 1


if __name__ == "__main__":
    sys.exit(main())
