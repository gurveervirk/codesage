import importlib.metadata
import requests
from typing import List, Dict, Optional, Any
from packaging.requirements import Requirement

# Re-export PackageNotFoundError for convenience
PackageNotFoundError = importlib.metadata.PackageNotFoundError

def fetch_pypi_metadata(package_name: str, version: str) -> Optional[Dict[str, Any]]:
    """
    Fetch metadata from PyPI JSON API.
    """
    url = f"https://pypi.org/pypi/{package_name}/{version}/json"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            return response.json()
    except Exception:
        pass
    return None

def extract_python_versions_from_classifiers(classifiers: List[str]) -> List[str]:
    """
    Extract Python versions from classifiers.
    e.g. "Programming Language :: Python :: 3.7" -> "3.7"
    """
    versions = []
    prefix = "Programming Language :: Python :: "
    for c in classifiers:
        if c.startswith(prefix):
            ver = c[len(prefix):].strip()
            # We only want version numbers like "3.7", "3.8", not "3" or "Implementation..."
            # But "3" is sometimes useful if no specific versions are listed.
            # For now, let's collect all that look like version numbers.
            parts = ver.split('.')
            if parts[0].isdigit():
                versions.append(ver)
    return sorted(list(set(versions)))

def get_package_metadata(package_name: str, version: str) -> Dict[str, Any]:
    """
    Get package metadata by reconciling local metadata with PyPI metadata.
    Returns a dictionary with:
    - python_requires: str (merged/reconciled)
    - supported_python_versions: List[str] (from classifiers)
    - dependencies: List[Dict] (merged)
    - extras: Dict (merged)
    """
    local_deps = get_package_dependencies(package_name)
    local_extras = get_package_extras(package_name)
    local_python_requires = get_package_python_requires(package_name)
    
    pypi_data = fetch_pypi_metadata(package_name, version)
    
    result = {
        "python_requires": local_python_requires,
        "supported_python_versions": [],
        "dependencies": local_deps,
        "extras": local_extras,
        "pypi_metadata_found": False
    }
    
    if pypi_data and "info" in pypi_data:
        result["pypi_metadata_found"] = True
        info = pypi_data["info"]
        
        # Reconcile Python Versions from Classifiers
        classifiers = info.get("classifiers", [])
        pypi_versions = extract_python_versions_from_classifiers(classifiers)
        result["supported_python_versions"] = pypi_versions
        
        # If local python_requires is missing, try to infer or use PyPI's
        if not result["python_requires"] and info.get("requires_python"):
            result["python_requires"] = info.get("requires_python")
            
        # Reconcile Dependencies
        # PyPI requires_dist is a list of strings
        pypi_requires_dist = info.get("requires_dist", [])
        if pypi_requires_dist:
            pypi_deps = []
            for req_str in pypi_requires_dist:
                try:
                    req = Requirement(req_str)
                    dep_info = {
                        "name": req.name,
                        "specifier": str(req.specifier),
                        "marker": str(req.marker) if req.marker else None,
                        "extras": list(req.extras)
                    }
                    pypi_deps.append(dep_info)
                except Exception:
                    pass
            
            # Merge strategy: 
            # If local deps are empty but PyPI has them, use PyPI.
            # If both have them, prefer local as it reflects installed reality, 
            # but maybe flag discrepancies? For now, let's just union them if local is empty.
            if not result["dependencies"] and pypi_deps:
                result["dependencies"] = pypi_deps
                
            # Also check for extras in PyPI if local is empty
            # (Note: extracting extras from requires_dist is complex as they are embedded in markers)
            # But we can try to parse them if needed. 
            # For now, we rely on local extras extraction which is usually accurate for installed packages.

    return result

def get_package_distribution(package_name: str) -> importlib.metadata.Distribution:
    """
    Get the distribution object for a package.
    """
    return importlib.metadata.distribution(package_name)

def get_package_version(package_name: str) -> str:
    """
    Get the version of a package.
    """
    return importlib.metadata.version(package_name)

def get_packages_distributions() -> Dict[str, List[str]]:
    """
    Get a mapping of top-level packages to distribution names.
    Safe wrapper that returns empty dict if not available (Python < 3.10).
    """
    if hasattr(importlib.metadata, 'packages_distributions'):
        return importlib.metadata.packages_distributions()
    return {}

def get_distribution_top_level_modules(package_name: str) -> List[str]:
    """
    Get top-level modules for a package using metadata.
    Supports Python 3.10+ packages_distributions() and fallback to top_level.txt.
    """
    modules = []
    
    # Try packages_distributions (Python 3.10+)
    if hasattr(importlib.metadata, 'packages_distributions'):
        try:
            mapping = importlib.metadata.packages_distributions()
            for top_module, distributions in mapping.items():
                if package_name in distributions:
                    if top_module not in modules:
                        modules.append(top_module)
            
            # If we found modules via packages_distributions, return them
            # But sometimes packages_distributions might miss things? 
            # Usually it's more reliable than top_level.txt which might be missing.
            if modules:
                return modules
        except Exception:
            pass
            
    # Fallback to top_level.txt
    try:
        dist = importlib.metadata.distribution(package_name)
        top_level_txt = dist.read_text('top_level.txt')
        if top_level_txt:
            for line in top_level_txt.strip().split('\n'):
                mod = line.strip()
                if mod and mod not in modules:
                    modules.append(mod)
    except Exception:
        pass
        
    return modules

def get_package_python_requires(package_name: str) -> Optional[str]:
    """
    Get the Python version requirements for a package.
    """
    try:
        dist = get_package_distribution(package_name)
        return dist.metadata.get('Requires-Python')
    except importlib.metadata.PackageNotFoundError:
        return None

def get_package_dependencies(package_name: str) -> List[Dict[str, Any]]:
    """
    Get all dependencies of a package as declared in Requires-Dist.
    
    Returns:
        A list of dictionaries containing dependency details:
        - name: The name of the dependency
        - specifier: The version specifier (e.g., ">=1.0")
        - marker: The environment marker (e.g., "extra == 'test'")
        - extras: Extras requested for the dependency (e.g., "requests[security]")
    """
    try:
        dist = get_package_distribution(package_name)
        requires = dist.requires
        if not requires:
            return []
        
        dependencies = []
        for req_str in requires:
            req = Requirement(req_str)
            dep_info = {
                "name": req.name,
                "specifier": str(req.specifier),
                "marker": str(req.marker) if req.marker else None,
                "extras": list(req.extras)
            }
            dependencies.append(dep_info)
            
        return dependencies
    except importlib.metadata.PackageNotFoundError:
        return []

def get_package_extras(package_name: str) -> Dict[str, List[Dict[str, Any]]]:
    """
    Get the extras of a package and their specific dependencies.
    
    Returns:
        A dictionary where keys are extra names and values are lists of dependencies 
        that are required when that extra is activated.
    """
    try:
        dist = get_package_distribution(package_name)
        # 'Provides-Extra' gives the list of extra names
        provided_extras = dist.metadata.get_all('Provides-Extra') or []
        
        requires = dist.requires or []
        
        extras_deps = {extra: [] for extra in provided_extras}
        
        for req_str in requires:
            req = Requirement(req_str)
            
            if req.marker:
                # Check if this is a base dependency (required even without extras)
                # We use an empty string for 'extra' to simulate no extra selected.
                # Note: evaluate() merges with default_environment(), so other markers 
                # (like python_version) are evaluated against the current system.
                try:
                    is_base = req.marker.evaluate({'extra': ''})
                except Exception:
                    # If evaluation fails, assume it's not a base dependency to be safe,
                    # or maybe it is? Let's assume False so we check extras.
                    is_base = False

                if not is_base:
                    for extra in provided_extras:
                        try:
                            if req.marker.evaluate({'extra': extra}):
                                dep_info = {
                                    "name": req.name,
                                    "specifier": str(req.specifier),
                                    "marker": str(req.marker)
                                }
                                extras_deps[extra].append(dep_info)
                        except Exception:
                            pass
            
        return extras_deps
    except importlib.metadata.PackageNotFoundError:
        return {}
