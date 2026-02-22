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
import subprocess
import sys
import os
import shutil
import logging
import argparse
import traceback
import re
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'backend'))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Import static analysis tools
try:
    from core.com_extractor import process_package_from_module_paths
    from core.com_extractor.models import Entity, Relationship
except ImportError as e:
    logger.error(f"Failed to import static analysis tools: {e}")
    process_package_from_module_paths = None

try:
    from core.com_store.graph.main import COMStore as _GraphStore
except ImportError:
    _GraphStore = None
        
try:
    from core.com_store.postgres.main import PostgresCOMStore as _PostgresStore
except ImportError:
    _PostgresStore = None

if not _GraphStore and not _PostgresStore:
    logger.warning("Neither GraphStore nor PostgresStore could be imported.")

# Global Stores
_stores = {}


def init_stores(config: Dict, targets: List[str] = None):
    """Initialize enabled COMStores."""
    global _stores
    targets = targets or ['neo4j']
    
    # Initialize Neo4j
    if 'neo4j' in targets and _GraphStore:
        if 'neo4j' not in _stores:
            logger.info(f"Initializing Neo4j COMStore connection to {config.get('neo4j_url')}")
            init_kwargs = {
                'username': config.get('neo4j_username', 'neo4j'),
                'password': config.get('neo4j_password', 'password'),
                'url': config.get('neo4j_url', 'bolt://localhost:7687'),
                'database': config.get('neo4j_database', 'neo4j'),
            }
            if config.get('batch_size'):
                init_kwargs['batch_size'] = config['batch_size']
            _stores['neo4j'] = _GraphStore(**init_kwargs)
            
    # Initialize Postgres
    if 'postgres' in targets and _PostgresStore:
        if 'postgres' not in _stores:
            logger.info(f"Initializing Postgres COMStore")
            conn_str = config.get('postgres_url')
            if not conn_str:
                logger.warning("Postgres URL not provided, skipping Postgres initialization")
            else:
                pg_store = _PostgresStore(connection_string=conn_str)
                try:
                    logger.info("Ensuring Postgres schema exists...")
                    pg_store.init_schema()
                except Exception as e:
                    logger.warning(f"Could not initialize Postgres schema: {e}")
                _stores['postgres'] = pg_store
    
    return _stores


def close_stores():
    """Close all COMStore connections."""
    global _stores
    if 'neo4j' in _stores:
        logger.info("Closing Neo4j connection")
        try:
            _stores['neo4j']._driver.close()
        except:
            pass
    _stores = {}


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
        required_dependencies = ["pydantic", "packaging", "requests"]
        cmd = [str(python_exe), "-m", "pip", "install", "--quiet", package_spec, *required_dependencies]
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


def _iter_python_minor_versions(start_version: str = "3.13", min_version: str = "3.8") -> List[str]:
    def _parse_minor(v: str) -> Tuple[int, int]:
        parts = v.split(".")
        major = int(parts[0]) if parts else 3
        minor = int(parts[1]) if len(parts) > 1 else 13
        return major, minor

    start_major, start_minor = _parse_minor(start_version)
    min_major, min_minor = _parse_minor(min_version)

    if start_major != min_major:
        raise ValueError("Python probe range must stay within the same major version")
    if start_minor < min_minor:
        raise ValueError("Start Python version must be >= minimum Python version")

    return [f"{start_major}.{minor}" for minor in range(start_minor, min_minor - 1, -1)]


def _find_available_python_executable() -> Optional[str]:
    candidates = [sys.executable, "python3", "python"]
    for candidate in candidates:
        try:
            subprocess.run([candidate, "--version"], capture_output=True, text=True, check=True)
            subprocess.run([candidate, "-m", "pip", "--version"], capture_output=True, text=True, check=True)
            return candidate
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue
    return None


def _uv_available() -> bool:
    try:
        subprocess.run(["uv", "--version"], check=True, capture_output=True, text=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def _select_wheel_file(download_dir: Path, library: str) -> Optional[Path]:
    wheels = sorted(download_dir.glob("*.whl"))
    if not wheels:
        return None

    normalized_library = re.sub(r"[-_.]+", "-", library).lower()
    for wheel in wheels:
        dist_name = wheel.name.split("-")[0]
        normalized_dist = re.sub(r"[-_.]+", "-", dist_name).lower()
        if normalized_dist == normalized_library:
            return wheel

    return wheels[0]


def download_wheel_without_deps(
    library: str,
    version: str,
    artifacts_dir: Path,
    start_python_version: str = "3.13",
    min_python_version: str = "3.8",
) -> Optional[Tuple[str, str, Path]]:
    package_spec = f"{library}=={version}"
    probe_versions = _iter_python_minor_versions(start_python_version, min_python_version)
    python_exe = _find_available_python_executable()
    if not python_exe:
        logger.error("No available Python executable found for wheel probing")
        return None

    logger.info(f"Using interpreter '{python_exe}' to probe wheel compatibility across Python versions")

    for py_minor in probe_versions:
        download_dir = artifacts_dir / f"download_{library}_{version}_{py_minor.replace('.', '_')}"
        if download_dir.exists():
            shutil.rmtree(download_dir)
        download_dir.mkdir(parents=True, exist_ok=True)

        py_tag = py_minor.replace(".", "")

        cmd = [
            python_exe,
            "-m",
            "pip",
            "download",
            "--only-binary=:all:",
            "--no-deps",
            "--implementation",
            "cp",
            "--python-version",
            py_tag,
            "--dest",
            str(download_dir),
            package_spec,
        ]

        try:
            logger.info(f"Attempting wheel download for {package_spec} with Python {py_minor}")
            subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=600)
        except subprocess.CalledProcessError as e:
            stderr = (e.stderr or "").strip()
            logger.info(f"Wheel download failed for Python {py_minor}: {stderr}")
            continue
        except subprocess.TimeoutExpired:
            logger.info(f"Wheel download timed out for Python {py_minor}")
            continue

        wheel_path = _select_wheel_file(download_dir, library)
        if not wheel_path:
            logger.info(f"No wheel file found after successful download command for Python {py_minor}")
            continue

        return python_exe, py_minor, wheel_path

    return None


def probe_installable_python_version(
    library: str,
    version: str,
    start_python_version: str = "3.13",
    min_python_version: str = "3.8",
) -> Optional[str]:
    package_spec = f"{library}=={version}"
    probe_versions = _iter_python_minor_versions(start_python_version, min_python_version)

    if _uv_available():
        for py_minor in probe_versions:
            cmd = [
                "uv",
                "pip",
                "install",
                "--dry-run",
                "--no-deps",
                "--python-version",
                py_minor,
                package_spec,
            ]
            try:
                logger.info(f"Attempting install dry-run for {package_spec} with Python {py_minor} via uv")
                subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=600)
                return py_minor
            except subprocess.CalledProcessError as e:
                stderr = (e.stderr or "").strip()
                logger.info(f"Install dry-run failed for Python {py_minor}: {stderr}")
                continue
            except subprocess.TimeoutExpired:
                logger.info(f"Install dry-run timed out for Python {py_minor}")
                continue
    else:
        python_exe = _find_available_python_executable()
        if not python_exe:
            return None
        for py_minor in probe_versions:
            cmd = [
                python_exe,
                "-m",
                "pip",
                "install",
                "--dry-run",
                "--no-deps",
                "--python-version",
                py_minor.replace(".", ""),
                package_spec,
            ]
            try:
                logger.info(f"Attempting install dry-run for {package_spec} with Python {py_minor}")
                subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=600)
                return py_minor
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                continue

    return None


def dry_run_install_for_python_version(
    library: str,
    version: str,
    python_minor: str,
) -> bool:
    package_spec = f"{library}=={version}"

    if _uv_available():
        cmd = [
            "uv",
            "pip",
            "install",
            "--dry-run",
            "--no-deps",
            "--python-version",
            python_minor,
            package_spec,
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=600)
            return True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return False

    python_exe = _find_available_python_executable()
    if not python_exe:
        return False

    cmd = [
        python_exe,
        "-m",
        "pip",
        "install",
        "--dry-run",
        "--no-deps",
        "--python-version",
        python_minor.replace(".", ""),
        package_spec,
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=600)
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False


def get_site_packages_path(venv_path: Path) -> Path:
    if sys.platform == "win32":
        site_packages = venv_path / "Lib" / "site-packages"
    else:
        lib_dir = venv_path / "lib"
        if not lib_dir.exists():
            sp = list(venv_path.rglob("site-packages"))
            if sp:
                return sp[0]
            raise FileNotFoundError(f"Could not find lib directory in {venv_path}")
        python_dirs = list(lib_dir.glob("python*"))
        if not python_dirs:
            raise FileNotFoundError(f"Could not find python directory in {lib_dir}")
        site_packages = sorted(python_dirs)[-1] / "site-packages"

    if not site_packages.exists():
        raise FileNotFoundError(f"site-packages not found at {site_packages}")

    return site_packages


def _discover_module_paths_from_site_packages(site_packages: Path, library: str) -> Dict[str, str]:
    module_names: List[str] = []
    normalized_library = re.sub(r"[-_.]+", "-", library).lower()

    dist_infos = []
    for dist_info_dir in sorted(site_packages.glob("*.dist-info")):
        dist_name = dist_info_dir.name.split("-")[0]
        normalized_dist = re.sub(r"[-_.]+", "-", dist_name).lower()
        if normalized_dist == normalized_library:
            dist_infos.append(dist_info_dir)

    if not dist_infos:
        dist_infos = sorted(site_packages.glob("*.dist-info"))

    for dist_info_dir in dist_infos:
        top_level_file = dist_info_dir / "top_level.txt"
        if top_level_file.exists():
            for raw_line in top_level_file.read_text(encoding="utf-8", errors="ignore").splitlines():
                module_name = raw_line.strip()
                if module_name and not module_name.startswith("#") and module_name not in module_names:
                    module_names.append(module_name)

    library_candidates = [library, library.replace("-", "_")]
    for candidate in library_candidates:
        if candidate not in module_names:
            module_names.append(candidate)

    module_paths: Dict[str, str] = {}
    for module_name in module_names:
        possible_names = [module_name, module_name.replace("-", "_")]
        for possible in possible_names:
            dir_path = site_packages / possible
            file_path = site_packages / f"{possible}.py"
            if dir_path.exists():
                module_paths[module_name] = str(dir_path)
                break
            if file_path.exists():
                module_paths[module_name] = str(file_path)
                break

    return module_paths


def create_env_with_python_version(venv_path: Path, python_version: str) -> bool:
    if _uv_available():
        try:
            logger.info(f"Creating environment at {venv_path} with Python {python_version} via uv")
            subprocess.run(
                ["uv", "venv", "--python", python_version, str(venv_path)],
                check=True,
                capture_output=True,
                text=True,
                timeout=600,
            )
            return True
        except subprocess.CalledProcessError as e:
            stderr = (e.stderr or "").strip()
            logger.warning(f"uv venv creation failed for Python {python_version}: {stderr}")
        except subprocess.TimeoutExpired:
            logger.warning(f"uv venv creation timed out for Python {python_version}")

    return create_venv(
        venv_path,
        use_conda=False,
        use_available_python=False,
        python_version=python_version,
    )


def install_package_in_env(venv_path: Path, package_spec: str) -> bool:
    python_exe = get_venv_python(venv_path)
    if _uv_available():
        try:
            logger.info(f"Installing {package_spec} in {venv_path} via uv")
            subprocess.run(
                ["uv", "pip", "install", "--no-deps", "-p", str(python_exe), package_spec],
                check=True,
                capture_output=True,
                text=True,
                timeout=1200,
            )
            return True
        except subprocess.CalledProcessError as e:
            stderr = (e.stderr or "").strip()
            logger.warning(f"uv install failed for {package_spec}: {stderr}")
        except subprocess.TimeoutExpired:
            logger.warning(f"uv install timed out for {package_spec}")
        return False

    return install_package(venv_path, package_spec)


def run_extraction_from_installed_env(
    venv_path: Path,
    library: str,
    version: str,
) -> Optional[tuple]:
    try:
        if not process_package_from_module_paths:
            raise ImportError("Static analysis tools not loaded")

        site_packages = get_site_packages_path(venv_path)
        logger.info(f"Using site-packages for extraction: {site_packages}")

        module_paths = _discover_module_paths_from_site_packages(site_packages, library)
        if not module_paths:
            logger.error(f"No top-level module paths discovered in installed env for {library}=={version}")
            return None

        logger.info(f"Discovered {len(module_paths)} top-level module path(s) from installed env: {sorted(module_paths.keys())}")
        result = process_package_from_module_paths(library, version, module_paths)

        logger.info(
            f"Extracted {len(result.entities)} entities, {len(result.relations)} structural relations, "
            f"and {sum(len(v) for v in result.other_relations.values())} other_relations via installed static extraction"
        )

        return (
            result.entities,
            result.relations,
            result.other_relations,
            getattr(result, "aliases", {}),
        )
    except Exception as e:
        logger.error(f"Static extraction from installed env failed: {e}")
        traceback.print_exc()
        return None


def _unpack_wheel(wheel_path: Path, unpack_dir: Path) -> None:
    if unpack_dir.exists():
        shutil.rmtree(unpack_dir)
    unpack_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(wheel_path, "r") as wheel_zip:
        wheel_zip.extractall(unpack_dir)


def _discover_module_paths_from_unpacked_wheel(unpack_dir: Path, library: str) -> Dict[str, str]:
    module_names: List[str] = []

    for dist_info_dir in sorted(unpack_dir.glob("*.dist-info")):
        top_level_file = dist_info_dir / "top_level.txt"
        if top_level_file.exists():
            for raw_line in top_level_file.read_text(encoding="utf-8", errors="ignore").splitlines():
                module_name = raw_line.strip()
                if module_name and not module_name.startswith("#") and module_name not in module_names:
                    module_names.append(module_name)

    if not module_names:
        for child in sorted(unpack_dir.iterdir()):
            name = child.name
            if name.endswith(".dist-info") or name.endswith(".data"):
                continue
            if child.is_dir():
                module_names.append(name)
            elif child.is_file() and child.suffix == ".py":
                module_names.append(child.stem)

    library_candidates = [library, library.replace("-", "_")]
    for candidate in library_candidates:
        if candidate not in module_names:
            module_names.append(candidate)

    module_paths: Dict[str, str] = {}
    for module_name in module_names:
        possible_names = [module_name, module_name.replace("-", "_")]
        for possible in possible_names:
            dir_path = unpack_dir / possible
            file_path = unpack_dir / f"{possible}.py"
            if dir_path.exists():
                module_paths[module_name] = str(dir_path)
                break
            if file_path.exists():
                module_paths[module_name] = str(file_path)
                break

    return module_paths


def run_extraction_from_wheel(
    library: str,
    version: str,
    wheel_path: Path,
    artifacts_dir: Path,
) -> Optional[tuple]:
    try:
        if not process_package_from_module_paths:
            raise ImportError("Static analysis tools not loaded")

        unpack_dir = artifacts_dir / f"unpacked_{wheel_path.stem}"
        _unpack_wheel(wheel_path, unpack_dir)

        module_paths = _discover_module_paths_from_unpacked_wheel(unpack_dir, library)
        if not module_paths:
            logger.error(f"No top-level module paths discovered in wheel {wheel_path.name}")
            return None

        logger.info(f"Discovered {len(module_paths)} top-level module path(s) from wheel: {sorted(module_paths.keys())}")

        result = process_package_from_module_paths(library, version, module_paths)

        logger.info(
            f"Extracted {len(result.entities)} entities, {len(result.relations)} structural relations, "
            f"and {sum(len(v) for v in result.other_relations.values())} other_relations via wheel static extraction"
        )

        return (
            result.entities,
            result.relations,
            result.other_relations,
            getattr(result, "aliases", {}),
        )

    except Exception as e:
        logger.error(f"Static extraction from wheel failed: {e}")
        traceback.print_exc()
        return None


def check_version_exists(
    library: str,
    version: str,
    config: Dict,
    targets: List[str]
) -> bool:
    """
    Check if a library version already exists in the enabled databases.
    Returns True only if it exists in ALL enabled targets.
    """
    stores = init_stores(config, targets)
    exists_all = True
    
    # Check Neo4j
    if 'neo4j' in stores:
        try:
            version_label = f"version_{version.replace('.', '_').replace(':', '_').replace('-', '_')}"
            check_query = """
            MATCH (root:DISTRIBUTION_PACKAGE {name: $library_name})
            WHERE $version_label IN labels(root)
            RETURN count(root) > 0 AS exists
            """
            result = stores['neo4j'].structured_query(check_query, {
                "library_name": library,
                "version_label": version_label
            })
            if not (result and result[0]['exists']):
                exists_all = False
        except Exception as e:
            logger.error(f"Error checking neo4j for {library}=={version}: {e}")
            exists_all = False

    # Check Postgres
    if 'postgres' in stores:
        try:
            pg_store = stores['postgres']
            with pg_store._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT 1
                        FROM entities e
                        JOIN entity_versions ev ON ev.entity_id = e.id
                        JOIN versions v ON v.id = ev.version_id
                        WHERE e.name = %s
                          AND 'DISTRIBUTION_PACKAGE' = ANY(e.types)
                          AND v.version_text = %s
                        LIMIT 1
                        """,
                        (library, version)
                    )
                    if not cur.fetchone():
                        exists_all = False
        except Exception as e:
            logger.error(f"Error checking postgres for {library}=={version}: {e}")
            exists_all = False
            
    return exists_all and len(stores) > 0


def upload_to_stores(
    entities: List,
    relations: List,
    other_relations: Dict,
    aliases: Dict,
    library: str,
    version: str,
    config: Dict,
    targets: List[str]
) -> bool:
    """
    Upload extracted entities to enabled databases.
    """
    stores = init_stores(config, targets)
    success = True
    
    # Upload to Neo4j
    if 'neo4j' in stores:
        try:
            logger.info(f"Uploading to Neo4j for {library}=={version}")
            stores['neo4j'].upsert_to_neo4j(
                module_name=library,
                entities=entities,
                relations=relations,
                other_relations=other_relations,
            )
        except Exception as e:
            logger.error(f"Failed to upload to Neo4j: {e}")
            traceback.print_exc()
            success = False

    # Upload to Postgres
    if 'postgres' in stores:
        try:
            logger.info(f"Uploading entities + other_relations + aliases to Postgres for {library}=={version}")
            stores['postgres'].upsert_to_postgres(
                entities=entities,
                other_relations=other_relations,
                aliases=aliases, 
                version=version
            )
        except Exception as e:
            logger.error(f"Failed to upload to Postgres: {e}")
            traceback.print_exc()
            success = False
            
    return success


def process_library_version(
    library: str,
    version: str,
    additional_deps: List[Dict],
    work_dir: Path,
    deputy_root: Path,
    config: Dict,
    targets: List[str],
    keep_venv: bool = False,
    use_conda: bool = False,
    use_available_python: bool = False,
    python_version: str = "3.13"
) -> bool:
    """
    Process a single library version.
    """
    artifacts_dir = work_dir / "wheel_artifacts"
    fallback_venv_path: Optional[Path] = None
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    
    try:
        if additional_deps:
            logger.info(f"Skipping {len(additional_deps)} additional dependency install(s) in wheel-only static mode")

        wheel_download = download_wheel_without_deps(
            library=library,
            version=version,
            artifacts_dir=artifacts_dir,
            start_python_version=python_version,
            min_python_version="3.8",
        )
        if not wheel_download:
            logger.warning(
                f"No compatible wheel found for {library}=={version}; falling back to install probe across Python versions"
            )

            extraction_result = None
            package_spec = f"{library}=={version}"
            for candidate_python in _iter_python_minor_versions(python_version, "3.8"):
                logger.info(
                    f"Probing fallback install path for {package_spec} with Python {candidate_python}"
                )

                if not dry_run_install_for_python_version(library, version, candidate_python):
                    logger.info(f"Dry-run rejected for Python {candidate_python}")
                    continue

                candidate_venv_path = work_dir / (
                    f"venv_{library}_{version.replace('.', '_')}_{candidate_python.replace('.', '_')}"
                )
                if candidate_venv_path.exists():
                    shutil.rmtree(candidate_venv_path)

                if not create_env_with_python_version(candidate_venv_path, candidate_python):
                    logger.info(f"Failed to create env for Python {candidate_python}; trying next")
                    continue

                if not install_package_in_env(candidate_venv_path, package_spec):
                    logger.info(f"Install failed for Python {candidate_python}; trying next")
                    try:
                        shutil.rmtree(candidate_venv_path)
                    except Exception:
                        pass
                    continue

                fallback_venv_path = candidate_venv_path
                logger.info(
                    f"Fallback install succeeded for {package_spec} with Python {candidate_python}"
                )
                extraction_result = run_extraction_from_installed_env(
                    venv_path=fallback_venv_path,
                    library=library,
                    version=version,
                )
                if extraction_result is not None:
                    break

                logger.info(f"Extraction failed after install for Python {candidate_python}; trying next")
                try:
                    shutil.rmtree(candidate_venv_path)
                except Exception:
                    pass

            if extraction_result is None:
                logger.error(f"No compatible install target found for {library}=={version} in Python probe range")
                return False

            entities, relations, other_relations, aliases = extraction_result

            if not upload_to_stores(entities, relations, other_relations, aliases, library, version, config, targets):
                return False

            logger.info(f"✓ Successfully processed {library}=={version}")
            return True

        python_exe, python_minor, wheel_path = wheel_download
        logger.info(
            f"Using wheel {wheel_path.name} downloaded with {python_exe} (Python {python_minor}) for {library}=={version}"
        )

        extraction_result = run_extraction_from_wheel(
            library=library,
            version=version,
            wheel_path=wheel_path,
            artifacts_dir=artifacts_dir,
        )
        if extraction_result is None:
            return False
        
        entities, relations, other_relations, aliases = extraction_result
        
        if not upload_to_stores(entities, relations, other_relations, aliases, library, version, config, targets):
            return False
        
        logger.info(f"✓ Successfully processed {library}=={version}")
        return True
        
    except Exception as e:
        logger.error(f"Error processing {library}=={version}: {e}")
        traceback.print_exc()
        return False
    
    finally:
        if not keep_venv and artifacts_dir.exists():
            logger.info(f"Cleaning up wheel artifacts under {artifacts_dir}")
            try:
                shutil.rmtree(artifacts_dir)
            except Exception as e:
                logger.warning(f"Failed to remove wheel artifacts: {e}")
        if not keep_venv and fallback_venv_path and fallback_venv_path.exists():
            logger.info(f"Cleaning up fallback venv at {fallback_venv_path}")
            try:
                shutil.rmtree(fallback_venv_path)
            except Exception as e:
                logger.warning(f"Failed to remove fallback venv: {e}")


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
            deputy_root=deputy_root,
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
