# Copilot Instructions for LibSage

This guide helps AI coding agents work productively in the LibSage monorepo. It covers architecture, workflows, and conventions unique to this project.

## Architecture Overview
- **Backend (`backend/`)**: Python services for workflow orchestration, type inspection, and agent logic. Key modules:
  - `app.py`: Main entrypoint for backend API.
  - `lib_sage/`: Core logic, including `reflex/` (type/model inspection), `sage_workflow/` (workflow/agent orchestration), and `com_store/` (communication store).
  - `routes/`: API endpoints for LLM, generation, uploads, etc.
  - `utils/`: Shared utilities and prompt templates.
- **Frontend (`frontend/`)**: Remix/React app for chat UI, context management, and agent interaction. Uses Tailwind CSS and Vite. Key files:
  - `app/`: Main app logic and components (e.g., `ChatInput.tsx`, `ContextManager.tsx`).
  - `utils/`, `routes/`: Frontend utilities and routing.
- **Jupyter Notebooks (`jupyter_nbs/`)**: Used for prototyping, testing type inspection, and workflow logic. Notebooks like `reflex_testing.ipynb` demonstrate backend type resolution.
- **MCP Integration (`backend/mcp/`)**: Contains MCP server templates and inspector tools for agent debugging and protocol compliance.

## Developer Workflows
- **Backend**
  - Install dependencies: `pip install -e .[dev]` or use `uv pip install -r pyproject.toml --extra dev`.
  - Run backend: `python backend/app.py` (or via VSCode debugger).
  - Test: Run Python tests in `backend/tests/`.
- **Frontend**
  - Install: `npm install` in `frontend/`.
  - Dev server: `npm run dev`.
  - Build: `npm run build`.
  - Start: `npm start` (after build).
- **Jupyter**
  - Use notebooks in `jupyter_nbs/` for type inspection and workflow prototyping.

## Project-Specific Patterns
- **Type Inspection**: Backend uses AST parsing and dynamic import resolution (see `reflex/` and `reflex_testing.ipynb`).
- **Workflow Orchestration**: Agents and workflows are defined in `sage_workflow/`, with events and multi-agent systems (`mas.py`).
- **Prompt Engineering**: Prompt templates are in `utils/prompts.py` and `utils/wkflw_prompts.py`.
- **API Routing**: All API endpoints are in `routes/`.
- **Frontend State**: Context and chat state managed in `frontend/app/ContextManager.tsx`.

## Integration Points
- **MCP Protocol**: Backend MCP server in `backend/mcp/` integrates with external agent builders and inspectors.
- **External Tools**: Uses Pydantic, typing, and custom AST logic for type resolution.
- **Frontend/Backend Communication**: Typically via REST endpoints in `routes/`.

## Conventions
- Use Python 3.9+ for backend (AST unparse required).
- Prefer `uv` for Python env management if available.
- Frontend uses Remix conventions and Tailwind for styling.
- All new workflows and agents should be placed in `sage_workflow/`.
- Notebooks are for prototyping only; production logic goes in Python modules.

## Examples
- See `reflex_testing.ipynb` for type inspection logic.
- See `sage_workflow/mas.py` for multi-agent orchestration.
- See `frontend/app/ChatInput.tsx` for chat UI patterns.

---

If any section is unclear or missing, please provide feedback so this guide can be improved for future AI agents.


# IMPORTANT INSTRUCTIONS
- Please do only what is asked no more no less.
- After every change/addition, reply in brief explaining what was done and ask if changes/additions to tests are needed.
- If you are unsure about something, ask for clarification before proceeding.
- Do not create extra Markdown files to explain your changes (NO SUMMARY or EXPLANATION files).