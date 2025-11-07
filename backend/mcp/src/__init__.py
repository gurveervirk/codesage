import os
import sys
from .server import server

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