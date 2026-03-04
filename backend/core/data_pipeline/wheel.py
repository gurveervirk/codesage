import subprocess
import shutil
import zipfile
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .env import _iter_python_minor_versions, _find_available_python_executable, _uv_available

logger = logging.getLogger(__name__)


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
        logger.info("No pip-capable Python executable found; wheel download skipped")
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
