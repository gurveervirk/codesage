# CodeSage

> **Archived.** CodeSage (January 2025 to March 2026) is the predecessor of [deputy](https://github.com/gurveervirk/deputy) and [deproc](https://github.com/gurveervirk/deproc). This repository is a snapshot of its Python and Neo4j design as of March 2026, published for reference. It is not maintained.

CodeSage builds a version-aware knowledge graph of Python libraries and uses it to ground AI code generation, so that agents write code against the APIs a library actually has in a given version instead of the ones a model remembers.

## How it works

| Part | Where | What it does |
|---|---|---|
| Code Object Model (COM) extractor | `backend/core/com_extractor` | Static analysis (AST and tree-sitter) plus runtime introspection (`inspect`) of installed packages. Extracts modules, classes, functions, methods, signatures, imports, aliases and inheritance |
| COM store | `backend/core/com_store` | Neo4j graph of the extracted entities, tracked across library versions with version diffs. Uniqueness constraints on content hashes (for `MERGE`), name indexes, and batched `UNWIND` upserts of 1,000 rows. Earlier versions also had full-text and vector indexes over LLM-written summaries and embeddings; these were replaced by regex queries in December 2025. Early PostgreSQL support |
| Data pipeline | `backend/core/data_pipeline` | Extracts and uploads a package version into the store |
| MCP server | `backend/mcp` | Exposes the graph to coding agents as `deputy_library_explorer` (named `codesage_library_explorer` until February 2026), with four tools: `search_definitions`, `list_libraries`, `get_definitions` and `get_api_call_path`. The store also has version-diff and library-map queries that the server does not expose; `backend/mcp/README.md` still lists them from an earlier plan |
| Multi-agent workflow | `backend/vault/sage_workflow` | Earlier LlamaIndex workflow: a RootAgent mediates and hands tasks to a SearchAgent (explores the graph) and a CodeAgent (writes code) through a shared scratchpad, each driven by its own system prompt (`backend/vault/utils/prompts.py`). It replaced the first agent, a Language Agent Tree Search (LATS) agent built on LlamaIndex's `LATSAgentWorker`, which explores candidate steps with Monte Carlo Tree Search and scores them with custom reflection and candidate-expansion prompts (February to March 2025, in the history from commit `1f494c7`) |
| API | `backend/app.py`, `backend/routes` | FastAPI backend for exploring the graph |
| Notebooks | `jupyter_nbs` | Where CodeSage started, including the original Colab prototype |

## Scale

A backup of the graph from September 2025, before version tracking was added, holds:

| | Count |
|---|---|
| Packages | 170: most of the Python standard library, plus numpy, requests, aerosandbox, casadi, Robot Framework, emoji and LlamaIndex |
| Entities | 37,060: 23,454 methods, 6,700 functions, 5,096 classes and 1,640 modules |
| Relationships | 92,284 |
| Entities with an LLM-written summary and a 1,024-dimension embedding | 25,134 |
| Indexes | 6 vector and 6 full-text, plus uniqueness constraints on entity IDs |

## Performance work

- **Index-backed relationship upserts (November 2025).** Relationship upserts originally matched both endpoints without a node label, so every row scanned the whole graph. Matching on a label lets Neo4j use an index instead. On the September 2025 graph, looking up both endpoints for 1,000 relationships took 31.6 s the old way and 0.04 s the new way, about 790 times faster (measured in November 2026 on Neo4j Community, from the server's own timing). Queries and upserts that had been impractically slow came down to about 10 seconds at most.
- **Batching (December 2025).** Upserts are sent in configurable `UNWIND` batches (1,000 rows by default), which fixed Neo4j running out of memory on large libraries.
- **Away from the graph database.** Exploring PostgreSQL `ltree` indexes for faster hierarchical path lookups led to the PostgreSQL-only store that followed this snapshot.

## Evaluation

**Execution test.** Each system got a single prompt per task with no retries, and the generated code was then run against the installed library. The code each system produced is in `jupyter_nbs/tests.ipynb` and `usage_validation/tests/test_cases`.

| Task | CodeSage | Gemini 2.0 Flash | GPT-4o |
|---|---|---|---|
| Aerosandbox: simple biplane | Ran | Failed (`ZeroDivisionError`) | not run |
| Aerosandbox: monoplane drag estimation | Ran (CL ≈ 0.47) | Failed (`AttributeError`: no `atmosphere.density`) | Failed (`TypeError`: no `reference_area` argument) |
| Robot Framework: extract keywords | Ran | Failed (`ImportError`) | Failed (`ImportError`) |

**Usage validation** (`usage_validation`). The same code was also checked statically: a custom checker finds every call into the external library, type stubs are generated from the signatures in CodeSage's graph, and mypy checks the code against them. Lower is better.

| Task | CodeSage | Gemini 2.0 Flash | GPT-4o |
|---|---|---|---|
| Aerosandbox: monoplane drag estimation | 1 error | 4 errors | 5 errors |
| Aerosandbox: simple biplane | 0 errors | 15 errors | not run |
| Robot Framework: extract keywords | 0 errors | 2 errors | 0 errors |

The static check misses some failures (GPT-4o's Robot Framework code passes it but fails to import), and its reference signatures come from CodeSage's own extraction. Three tasks is a small sample, so treat both as sanity checks, not a benchmark.

**GitChameleon** (`benchmarks/GitChameleonBenchmark`). In December 2025, Cline (GPT-4.1) used the MCP server to solve 8 version-specific Plotly samples from the [GitChameleon benchmark](https://arxiv.org/abs/2507.12367). The run notes are in `benchmarks/GitChameleonBenchmark/test_results/Cline/metadata.md`. No pass rate was computed, and the notes record two gaps: the tools did not account for library dependencies or Python-version constraints.

## How it evolved

- **Jan 2025:** started as CodeSage in Colab notebooks
- **Feb 2025:** first agent grounded in the graph, a LATS agent; replaced later that month by the three-agent workflow
- **Oct 2025:** CI and test suite
- **Nov 2025 to Jan 2026:** version tracking, version diffs, the MCP server, index-backed upserts and the GitChameleon run
- **Feb 2026:** renamed to Deputy, tree-sitter extraction, first PostgreSQL support
- **Mar 2026:** this snapshot

After this snapshot the project moved to a PostgreSQL-only store and added Java and TypeScript/JavaScript parsers. The analysis core then became [deproc](https://github.com/gurveervirk/deproc) and the tooling became the [deputy](https://github.com/gurveervirk/deputy) CLI.

## Running it

This snapshot is not maintained, and it depends on pinned versions from 2025-2026 (see `pyproject.toml`).

1. Install dependencies with [uv](https://github.com/astral-sh/uv): `uv sync`
2. Create `backend/.env` with `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD` and `GOOGLE_GENAI_API_KEY` (and optionally `SUPABASE_DB_URL` or `POSTGRES_URL`). Never commit this file
3. For the MCP server, follow `backend/mcp/README.md` and `backend/mcp/USER_GUIDE.md`

## License

[Apache License 2.0](LICENSE)
