# CodeSage

> **Archived.** CodeSage (January 2025 to March 2026) is the predecessor of [deputy](https://github.com/gurveervirk/deputy) and [deproc](https://github.com/gurveervirk/deproc). This repository is a snapshot of its Python and Neo4j design as of March 2026, published for reference. It is not maintained.

CodeSage builds a version-aware knowledge graph of Python libraries and uses it to ground AI code generation, so that agents write code against the APIs a library actually has in a given version instead of the ones a model remembers.

## How it works

| Part | Where | What it does |
|---|---|---|
| Code Object Model (COM) extractor | `backend/core/com_extractor` | Static analysis (AST and tree-sitter) plus runtime introspection (`inspect`) of installed packages. Extracts modules, classes, functions, methods, signatures, imports, aliases and inheritance |
| COM store | `backend/core/com_store` | Neo4j graph of the extracted entities, tracked across library versions with version diffs. Uniqueness constraints on content hashes (for `MERGE` performance), name, full-text and vector indexes, and batched `UNWIND` upserts. Early PostgreSQL support |
| Data pipeline | `backend/core/data_pipeline` | Extracts and uploads a package version into the store |
| MCP server | `backend/mcp` | Exposes the graph to coding agents as `deputy_library_explorer` (named `codesage_library_explorer` until February 2026), with four tools: `search_definitions`, `list_libraries`, `get_definitions` and `get_api_call_path`. The store also has version-diff and library-map queries that the server does not expose; `backend/mcp/README.md` still lists them from an earlier plan |
| Multi-agent workflow | `backend/vault/sage_workflow` | Earlier LlamaIndex workflow: a RootAgent mediates and hands tasks to a SearchAgent (explores the graph) and a CodeAgent (writes code) through a shared scratchpad, each driven by its own system prompt (`backend/vault/utils/prompts.py`) |
| API | `backend/app.py`, `backend/routes` | FastAPI backend for exploring the graph |
| Notebooks | `jupyter_nbs` | Where CodeSage started, including the original Colab prototype |

## Evaluation

**Usage validation** (`usage_validation`). Code generated for three real tasks was checked statically: a custom checker finds every call into the external library, type stubs are generated from the signatures in CodeSage's graph, and mypy checks the code against them. The code was not executed. Lower is better.

| Task | CodeSage | Gemini 2.0 | GPT-4o |
|---|---|---|---|
| Aerosandbox: monoplane drag estimation | 1 error | 4 errors | 5 errors |
| Aerosandbox: simple biplane | 0 errors | 15 errors | not run |
| Robot Framework: extract keywords | 0 errors | 2 errors | 0 errors |

Three tasks is a small sample, and the reference signatures come from CodeSage's own extraction, so treat this as a sanity check, not a benchmark.

**GitChameleon** (`benchmarks/GitChameleonBenchmark`). In December 2025, Cline (GPT-4.1) used the MCP server to solve 8 version-specific Plotly samples from the [GitChameleon benchmark](https://arxiv.org/abs/2507.12367). The run notes are in `benchmarks/GitChameleonBenchmark/test_results/Cline/metadata.md`. No pass rate was computed, and the notes record two gaps: the tools did not account for library dependencies or Python-version constraints.

## How it evolved

- **Jan 2025:** started as CodeSage in Colab notebooks
- **Feb 2025:** first working agent grounded in the graph
- **Oct 2025:** CI and test suite
- **Nov 2025 to Jan 2026:** version tracking, version diffs, the MCP server and the GitChameleon run
- **Feb 2026:** renamed to Deputy, tree-sitter extraction, first PostgreSQL support
- **Mar 2026:** this snapshot

After this snapshot the project moved to a PostgreSQL-only store and added Java and TypeScript/JavaScript parsers. The analysis core then became [deproc](https://github.com/gurveervirk/deproc) and the tooling became the [deputy](https://github.com/gurveervirk/deputy) CLI.

## Running it

This snapshot is not maintained, and it depends on pinned versions from 2025-2026 (see `pyproject.toml`).

1. Install dependencies with [uv](https://github.com/astral-sh/uv): `uv sync`
2. Create `backend/.env` with `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD` and `GOOGLE_GENAI_API_KEY` (and optionally `SUPABASE_DB_URL` or `POSTGRES_URL`). Never commit this file
3. For the MCP server, follow `backend/mcp/README.md` and `backend/mcp/USER_GUIDE.md`

## Contributors

Built by Gurveer Singh Virk, with early contributions from preetsarda and manthanvw in 2025.

## License

[Apache License 2.0](LICENSE)
