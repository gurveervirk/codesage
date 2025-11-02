import os
import sys
from typing import List, Optional
from mcp.server.fastmcp import FastMCP

# Add the backend directory to the Python path
backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, backend_path)

from lib_sage.com_store import COMStore
from config import config

# Initialize FastMCP server
server = FastMCP("codesage_library_explorer")

# Initialize COMStore with Neo4j connection
com_store = COMStore(
    url=config.NEO4J_URI,
    username=config.NEO4J_USER,
    password=config.NEO4J_PASSWORD,
    database="neo4j"
)


@server.tool()
async def get_version_diff(
    parent_entity: str,
    old_version: str,
    new_version: str,
    extra_props: Optional[List[str]] = None
) -> str:
    """
    Compare two versions of a library showing added, removed, and modified entities.
    
    Returns a git-style diff showing signature changes between versions with detailed statistics.
    """
    result = com_store.get_version_diff(parent_entity, old_version, new_version, extra_props)
    return result


@server.tool()
async def library_map(
    library_name: str,
    depth: int = 2,
    show_structure: bool = True,
    show_definitions: bool = True,
    page: int = 1,
    page_size: int = 50,
    extra_props: Optional[List[str]] = None,
    version: Optional[str] = None
) -> str:
    """
    Generate an ASCII tree structure and definition list for a library.
    
    Returns paginated library structure with functions, classes, and methods.
    """
    result = com_store.library_map(
        library_name, depth, show_structure, show_definitions,
        page, page_size, extra_props, version
    )
    return result


@server.tool()
async def search_definitions(
    parent_entity_name: str,
    search_terms: List[str],
    page: int = 1,
    page_size: int = 10
) -> str:
    """
    Search for functions, classes, and methods within a library.
    
    Supports partial matching and returns signatures with fully qualified names.
    """
    result = com_store.search_definitions(parent_entity_name, search_terms, page, page_size)
    return result


@server.tool()
async def list_libraries(extra_props: Optional[List[str]] = None) -> str:
    """
    List all Python libraries indexed in the knowledge graph.
    
    Returns library names and optional metadata for all indexed ROOT_MODULE entities.
    """
    result = com_store.list_libraries(extra_props)
    return result


@server.tool()
async def get_signatures(entity_names: List[str]) -> str:
    """
    Retrieve function/method signatures for specified entities.
    
    For classes, returns __init__ signature. Returns type and signature for each entity.
    """
    result = com_store.get_signatures(entity_names)
    return result


@server.tool()
async def get_full_path_names(names: List[str]) -> str:
    """
    Resolve entity names to their fully qualified paths.
    
    Returns exact matches or best candidates for disambiguation.
    """
    result = com_store.get_full_path_names(names)
    return result


@server.tool()
async def get_info_for_entities(entity_names: List[str]) -> str:
    """
    Get detailed metadata for specified entities from the knowledge graph.
    
    Returns all available properties and relationships for each entity.
    """
    result = com_store.get_info_for_entities(entity_names)
    return result
