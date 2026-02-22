import logging
import shutil
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from .env import (
    get_site_packages_path,
    _discover_module_paths_from_site_packages,
    create_env_with_python_version,
    install_package_in_env,
    _iter_python_minor_versions,
)
from .wheel import (
    download_wheel_without_deps,
    dry_run_install_for_python_version,
    _unpack_wheel,
    _discover_module_paths_from_unpacked_wheel,
)
from .stores import upload_to_stores

logger = logging.getLogger(__name__)

try:
    from core.com_extractor import process_package_from_module_paths
except ImportError as e:
    logger.error(f"Failed to import static analysis tools: {e}")
    process_package_from_module_paths = None


@dataclass
class ProcessingConfig:
    keep_venv: bool = False
    use_conda: bool = False
    use_available_python: bool = False
    python_version: str = "3.13"
    targets: List[str] = field(default_factory=lambda: ["neo4j"])
    store_config: Dict = field(default_factory=dict)


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

        logger.info(
            f"Discovered {len(module_paths)} top-level module path(s) from installed env: {sorted(module_paths.keys())}"
        )
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

        logger.info(
            f"Discovered {len(module_paths)} top-level module path(s) from wheel: {sorted(module_paths.keys())}"
        )

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


def process_library_version(
    library: str,
    version: str,
    additional_deps: List[Dict],
    work_dir: Path,
    config: Dict,
    targets: List[str],
    keep_venv: bool = False,
    use_conda: bool = False,
    use_available_python: bool = False,
    python_version: str = "3.13",
) -> bool:
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
                logger.info(f"Probing fallback install path for {package_spec} with Python {candidate_python}")

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
                logger.info(f"Fallback install succeeded for {package_spec} with Python {candidate_python}")
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
