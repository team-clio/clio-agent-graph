# Repository Guidelines

## Project Structure & Module Organization

This is a Python 3.11+ LangGraph agent server. Application code is in
`src/clio_agent_graph/`: `graph.py` is the stable server entrypoint;
`workflows/orchestration/` handles event routing; `workflows/reporting/`
contains normalization, retrieval, and matching; and `workflows/analysis/`
contains issue analysis. PCM, repository access, and read-only agent tools
live under `context/`. Shared LLM and tool-calling support lives under
`runtime/`. Tests are grouped by behavior under `tests/`. Runtime graph
configuration is in `langgraph.json`.

## Architecture & Convention References

When a task involves architectural decisions, workflow design, package boundaries, Agent/Tool
permissions, testing strategy, or runtime configuration, consult the relevant documents under
`convention/` as needed. Start with `convention/README.md`, which links to the detailed architecture,
LangGraph workflow, code, testing, and operations conventions. Keep these documents aligned with the
implementation whenever a change introduces or revises a project-wide convention.

## Build, Test, and Development Commands

Create an environment and install development plus LLM dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,llm]"
```

- `langgraph dev` starts the local agent server (after copying `.env.example` to `.env`).
- `pytest` runs the test suite; pytest is configured to discover `tests/` and use quiet output.
- `ruff check .` runs lint checks.
- `ruff format --check .` verifies formatting. Use `ruff format .` before committing when changes need formatting.

## Coding Style & Naming Conventions

Use four-space indentation, type annotations, and Python 3.11 syntax. Ruff enforces a
100-character line limit and rules for errors, imports, upgrades, bugbears, and simplification.
Use `snake_case` for modules, functions, variables, and test names; `PascalCase` for classes;
and uppercase `SCREAMING_SNAKE_CASE` for constants. Keep nodes focused on orchestration: expose
read operations through `tools/`, keep service implementations behind `services/`, and do not
give agents direct access to write operations.

## Testing Guidelines

Write pytest tests named `test_<behavior>()`, placing orchestration node tests in `tests/nodes/`
and cross-graph behavior in `tests/test_graph.py`. Exercise public graph inputs with representative
request payloads and assert both results and routing/terminal status. Add regression coverage for
every behavior change; there is no repository-wide coverage threshold configured.

## Commit & Pull Request Guidelines

Recent history uses short, imperative Conventional Commit-style subjects, such as
`feat: add tool-calling LLM agents`, `docs(graph): add Korean code comments`, and
`chore: ignore IDE project files`. Keep commits scoped and descriptive. Pull requests should
explain the graph or API behavior changed, link relevant issues, list validation commands run,
and include sample requests/responses or screenshots when they clarify observable behavior.

## Configuration & Secrets

Copy `.env.example` to `.env` for local configuration. Never commit API keys, LangSmith tokens,
or provider credentials. Prefer the deterministic mock fallback for tests; configure the global
`CLIO_MODEL` selection and the selected provider's credential only for live LLM runs.
