import subprocess
import sys
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def create_venv(
    venv_path: Path,
    use_conda: bool = False,
    use_available_python: bool = False,
    python_version: str = "3.13",
) -> bool:
    try:
        if use_conda:
            try:
                conda_result = subprocess.run(
                    ["conda", "--version"],
                    capture_output=True,
                    text=True,
                )
                if conda_result.returncode == 0:
                    logger.info(f"Using conda to create environment at {venv_path} with Python {python_version}")
                    subprocess.run(
                        ["conda", "create", "-p", str(venv_path), f"python={python_version}", "-y"],
                        check=True,
                        capture_output=True,
                    )
                    logger.info(f"Conda environment created at {venv_path}")
                    return True
            except (subprocess.CalledProcessError, FileNotFoundError) as e:
                logger.warning(f"Conda environment creation failed, falling back to venv: {e}")

        major_minor = ".".join(python_version.split(".")[:2])
        python_candidates = [f"python{major_minor}", "python3", "python"]
        python_exe = None

        for candidate in python_candidates:
            try:
                result = subprocess.run(
                    [candidate, "--version"],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                version_output = result.stdout.strip()
                if use_available_python:
                    python_exe = candidate
                    logger.info(f"Found Python: {version_output}")
                    break
                elif f"Python {major_minor}" in version_output:
                    python_exe = candidate
                    logger.info(f"Found Python {major_minor}: {version_output}")
                    break
            except (subprocess.CalledProcessError, FileNotFoundError):
                continue

        if not python_exe:
            if use_available_python:
                logger.error("No Python executable found.")
            else:
                logger.error(
                    f"Python {major_minor} not found. Please install Python {major_minor}, "
                    f"use --use-conda with --python-version, or use --use-available-python flag"
                )
            logger.error("Tried: " + ", ".join(python_candidates))
            return False

        logger.info(f"Creating virtual environment at {venv_path} using {python_exe}")
        subprocess.run(
            [python_exe, "-m", "venv", str(venv_path)],
            check=True,
            capture_output=True,
        )
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to create venv: {e.stderr.decode()}")
        return False


def get_venv_python(venv_path: Path) -> Path:
    if sys.platform == "win32":
        conda_python = venv_path / "python.exe"
        venv_python = venv_path / "Scripts" / "python.exe"
        return conda_python if conda_python.exists() else venv_python
    else:
        conda_python = venv_path / "bin" / "python"
        venv_python = venv_path / "bin" / "python"
        return conda_python if conda_python.exists() else venv_python


def install_package(venv_path: Path, package_spec: str) -> bool:
    python_exe = get_venv_python(venv_path)
    try:
        logger.info(f"Installing {package_spec}")
        required_dependencies = ["pydantic", "packaging", "requests"]
        cmd = [str(python_exe), "-m", "pip", "install", "--quiet", package_spec, *required_dependencies]
        subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            timeout=600,
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
