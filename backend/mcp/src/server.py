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

server.tool()(com_store.get_version_diff)
server.tool()(com_store.library_map)

@server.tool(description=com_store.search_definitions.__doc__)
def search_definitions(
    parent_entity_name: str,
    search_terms,
    page: int = 1,
    page_size: int = 10
):
    return com_store.search_definitions(
        parent_entity_name,
        search_terms,
        page,
        page_size
    )

@server.tool(description=com_store.list_libraries.__doc__)
def list_libraries(
    search_terms = None
):
    return com_store.list_libraries(
        search_terms
    )

@server.tool(description=com_store.get_definitions.__doc__)
def get_definitions(
    search_terms
):
    return com_store.get_definitions(
        search_terms
    )