import os
import sys
from mcp.server.fastmcp import FastMCP

# Add the backend directory to the Python path
backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, backend_path)

from core.com_store import COMStore, COMStoreTools
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
# Initialize COMStoreTools with the COMStore instance
com_store_tools = COMStoreTools(com_store)

# Register tools
server.tool()(com_store_tools.get_version_diff)
server.tool()(com_store_tools.library_map)

@server.tool(description=com_store_tools.search_definitions.__doc__)
def search_definitions(
    library: str,
    search_terms,
    version: str,
    parent_filters: str = None,
    page: int = 1,
    page_size: int = 10
):
    return com_store_tools.search_definitions(
        library=library,
        search_terms=search_terms,
        version=version,
        parent_filters=parent_filters,
        page=page,
        page_size=page_size
    )

@server.tool(description=com_store_tools.list_libraries.__doc__)
def list_libraries(
    search_terms = None
):
    return com_store_tools.list_libraries(
        search_terms=search_terms
    )

@server.tool(description=com_store_tools.get_definitions.__doc__)
def get_definitions(
    entity_names,
    version: str = None
):
    return com_store_tools.get_definitions(
        entity_names=entity_names,
        version=version
    )

@server.tool(description=com_store_tools.get_api_call_path.__doc__)
def get_api_call_path(
    entity_name: str,
    root_module: str = None,
    root_module_version: str = None,
    version_label: str = None
):
    return com_store_tools.get_api_call_path(
        entity_name=entity_name,
        root_module=root_module,
        root_module_version=root_module_version,
        version_label=version_label
    )

# Register resource - USER_GUIDE for contextual help
@server.resource("guide://user-guide")
def get_user_guide():
    """
    Get the complete User Guide for the CodeSage Library Explorer MCP Server.
    
    This resource provides comprehensive documentation on:
    - Available tools and their usage
    - Common workflows and scenarios
    - Use cases and examples
    - Tips for effective usage
    
    Use this as reference context to understand how to properly use the MCP server tools.
    """
    import os
    guide_path = os.path.join(os.path.dirname(__file__), "..", "USER_GUIDE.md")
    
    try:
        with open(guide_path, "r", encoding="utf-8") as f:
            guide_content = f.read()
        
        return {
            "uri": "guide://user-guide",
            "name": "CodeSage Library Explorer User Guide",
            "description": "Complete guide on using MCP server tools, workflows, and best practices",
            "mimeType": "text/markdown",
            "text": guide_content
        }
    except FileNotFoundError:
        return {
            "uri": "guide://user-guide",
            "name": "CodeSage Library Explorer User Guide",
            "description": "User guide not found",
            "mimeType": "text/plain",
            "text": "USER_GUIDE.md not found. Please ensure the guide is present in the mcp directory."
        }

def main():
    """Main entry point for the MCP server"""
    # Get transport type from command line args or default to streamable-http
    transport_type = sys.argv[1] if len(sys.argv) > 1 else "streamable-http"
    
    # Configure logging
    server.settings.log_level = os.environ.get("LOG_LEVEL", "INFO")
    
    if transport_type in ["streamable-http", "http"]:
        # Configure Streamable HTTP transport (modern, single-endpoint protocol)
        port = int(os.environ.get("PORT", 3001))
        host = os.environ.get("HOST", "127.0.0.1")
        
        server.settings.port = port
        server.settings.host = host
        
        print(f"Starting CodeSage Library Explorer MCP Server")
        print(f"Transport: Streamable HTTP (Modern MCP Protocol)")
        print(f"Endpoint: http://{host}:{port}/mcp")
        print(f"Log level: {server.settings.log_level}")
        print(f"\nStreamable HTTP provides:")
        print(f"  • Single endpoint for all MCP communication")
        print(f"  • Better proxy/load balancer compatibility")
        print(f"  • Full-duplex bidirectional streaming")
        
        # Run with Streamable HTTP transport (supersedes SSE)
        server.run(transport="streamable-http")
        
    elif transport_type == "sse":
        # Configure SSE (Server-Sent Events) transport for HTTP streaming (legacy)
        port = int(os.environ.get("PORT", 3001))
        host = os.environ.get("HOST", "127.0.0.1")
        
        server.settings.port = port
        server.settings.host = host
        
        print(f"Starting CodeSage Library Explorer MCP Server")
        print(f"Transport: SSE (Legacy HTTP Streaming)")
        print(f"Listening on: http://{host}:{port}")
        print(f"Log level: {server.settings.log_level}")
        print(f"\nNote: Consider using 'streamable-http' transport for new deployments")
        
        # Run with SSE transport (legacy)
        server.run(transport="sse")
        
    elif transport_type == "stdio":
        # Configure STDIO transport for direct process communication
        print(f"Starting CodeSage Library Explorer MCP Server")
        print(f"Transport: STDIO")
        print(f"Log level: {server.settings.log_level}")
        
        # Run with STDIO transport
        server.run(transport="stdio")
        
    else:
        print(f"Error: Invalid transport type '{transport_type}'")
        print("Usage: python -m src [streamable-http|sse|stdio]")
        print("  streamable-http - Use Streamable HTTP transport (recommended)")
        print("  sse             - Use Server-Sent Events (legacy)")
        print("  stdio           - Use standard input/output transport")
        sys.exit(1)

if __name__ == "__main__":
    main()