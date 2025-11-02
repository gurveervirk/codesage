# CodeSage Library Explorer MCP Server

This MCP Server provides tools for exploring and querying the CodeSage library knowledge graph. It exposes methods from the COMStore class to enable AI agents to search, compare, and analyze Python libraries indexed in Neo4j.

## Features

The server provides the following tools:

- **get_version_diff**: Compare two versions of a library showing added/removed/modified entities
- **library_map**: Generate an ASCII tree structure and definition list for a library
- **search_definitions**: Search for functions, classes, and methods within a library
- **list_libraries**: Get a list of all indexed libraries in the knowledge graph
- **get_signatures**: Retrieve function/method signatures for entities
- **get_full_path_names**: Resolve entity names to their fully qualified paths
- **get_info_for_entities**: Get comprehensive information about entities

## Prerequisites

To run the MCP Server, you will need:

- [Python](https://www.python.org/) 3.10 or higher
- Access to a Neo4j database with indexed library data
- (*Optional*) [uv](https://github.com/astral-sh/uv) for faster dependency management
- [Python Debugger Extension](https://marketplace.visualstudio.com/items?itemName=ms-python.debugpy)

## Environment Setup

### Configuration

Create a `.env` file in the `backend/` directory with your Neo4j credentials:

```env
NEO4J_URI=neo4j://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_password
```

### Install Dependencies

Choose one of the following approaches:

| Approach | Steps |
| -------- | ----- |
| Using `uv` | 1. Create virtual environment: `uv venv` <br>2. Run VSCode Command "***Python: Select Interpreter***" and select the python from created virtual environment <br>3. Install dependencies: `uv pip install -r pyproject.toml --extra dev` |
| Using `pip` | 1. Create virtual environment: `python -m venv .venv` <br>2. Run VSCode Command "***Python: Select Interpreter***" and select the python from created virtual environment<br>3. Install dependencies: `pip install -e .[dev]` | 

> Note: Reload VSCode or terminal after creating the virtual environment.

## Getting Started

After setting up the environment:

1. Open VS Code Debug panel
2. Select `Debug in Agent Builder` or press `F5` to start debugging
3. Use AI Toolkit Agent Builder to test the server
4. Click `Run` to test the server with your prompts

## Example Prompts

Here are some example prompts to test the MCP server:

- "List all indexed libraries"
- "Show me the structure of the numpy library"
- "Search for 'array' functions in numpy"
- "Compare version 1.0.0 and 2.0.0 of requests library"
- "Get the signature for numpy.ndarray"
- "What is the full path name for 'DataFrame'?"

## Project Structure

| Folder / File| Contents                                     |
| ------------ | -------------------------------------------- |
| `.vscode`    | VSCode files for debugging                   |
| `.aitk`      | Configurations for AI Toolkit                |
| `src`        | The source code for the MCP server           |
| `src/server.py` | Main server implementation with tool definitions |

## Debugging

> Note: All debugging modes support breakpoints in the tool implementation code.

| Debug Mode | Description | Steps |
| ---------- | ----------- | ----- |
| Agent Builder | Debug via AI Toolkit Agent Builder | 1. Open VS Code Debug panel<br>2. Select `Debug in Agent Builder` and press `F5`<br>3. Use AI Toolkit Agent Builder to test<br>4. Click `Run` to execute prompts |
| MCP Inspector | Debug using MCP Inspector | 1. Install [Node.js](https://nodejs.org/)<br>2. Set up Inspector: `cd inspector && npm install`<br>3. Select `Debug SSE in Inspector` and press `F5`<br>4. Click `Connect` in the browser<br>5. Test tools via the Inspector UI |

## Default Ports

| Debug Mode | Ports | Configuration Files | Customization |
| ---------- | ----- | ------------------- | ------------- |
| Agent Builder | 3001 | [tasks.json](.vscode/tasks.json) | Edit launch.json, tasks.json, \_\_init\_\_.py, mcp.json |
| MCP Inspector | 3001 (Server); 5173, 3000 (Inspector) | [tasks.json](.vscode/tasks.json) | Edit launch.json, tasks.json, \_\_init\_\_.py, mcp.json |

## Feedback

For feedback or suggestions, please open an issue on the [CodeSage GitHub repository](https://github.com/gurveervirk/CodeSage/issues)