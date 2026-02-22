# Deputy Library Explorer MCP Server Guide

### 1. \`list_libraries\`
- **Initial discovery**: Find what libraries are available in the database.
- **Version checking**: See which specific versions of a library are indexed.
- **Search**: Find libraries matching specific keywords or partial names.

### 2. \`library_map\`
- **Library exploration**: Get a high-level overview of the entire library structure.
- **API discovery**: Find all available modules, classes, and functions in a specific version.
- **Comparison preparation**: Understand the structure before performing version comparisons.
- **Documentation generation**: Extract a complete map of a library's API.

### 3. \`search_definitions\`
- **FQN retrieval**: Find the fully qualified name (FQN) of an entity using its simple name.
- **Targeted search**: Find specific functions or classes within a library or sub-package.
- **API exploration**: Discover available methods or classes matching a specific term.
- **Flexible matching**: Use parent filters to narrow down the search scope to specific modules or classes.
- **Pagination**: Efficiently handle and browse through large sets of search results.

### 4. \`get_definitions\`
- **Deep dive**: Get complete, detailed information about specific entities.
- **Signature inspection**: View function and method signatures with resolved type information.
- **Documentation retrieval**: Access full docstrings for modules, classes, and functions.
- **Multi-entity lookup**: Batch retrieve details for several entities in a single request.

### 5. \`get_version_diff\`
- **Migration planning**: Understand exactly what changed between two versions of a library.
- **Breaking changes**: Identify removed or modified APIs that might break existing code.
- **New features**: Discover newly added functionality in a more recent version.
- **API evolution**: Track how signatures and structures evolve over time.

### 6. \`get_api_call_path\`
- **Import help**: Find the correct and shortest import path for any entity.
- **API navigation**: Understand how to access deeply nested entities through the public API.
- **Path discovery**: Learn the recommended route to internal or sub-module entities.
- **Code generation**: Generate accurate import statements for use in scripts or applications.
