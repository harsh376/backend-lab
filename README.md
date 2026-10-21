# Backend Lab

## Posts

- October 19, 2026: [MCP tool over a durable agent](posts/2026-10-19-mcp-tool-durable-agent.md)

## Monorepo structure:

- FastAPI app: `apps/api/`
- MCP server and answer worker: `apps/mcp/`
- Temporal answer evaluations and LLM judging: `apps/evals/`
- React frontend: `apps/frontend/`
- Pure JS frontend: `apps/basic_frontend/`
- Python concepts: `apps/concepts/`
- Shared backend code (DB, Service-Repository-Domain, Observability): `backend/`
  - Core pattern: Service Layer + Repository with dependency injection
- Docker compose stacks: `compose/`
- IaC: `infra/`

## Quick start

Docker with the Compose plugin is required to run the application.

**Run the relevant stack**

```bash
docker compose -f compose/{stack}.yaml up --build
```

Additional Compose stacks should layer their overrides after the base file:

```bash
docker compose -f compose/base.yaml \
  -f compose/override.yaml \
  up --build
```

Compose automatically loads `compose/.env`. Copy `compose/.env.example` when
setting up a new checkout or when you want to restore the documented defaults.

For the answer and eval apps, run each stack in a separate terminal, in this
order. Wait for Elasticsearch and Temporal to become healthy before starting
the application stacks:

```bash
# Terminal 1
docker compose -f compose/elasticsearch.yaml up
# Terminal 2
docker compose -f compose/temporal.yaml up
# Terminal 3
docker compose -f compose/mcp.yaml up --build
# Terminal 4
docker compose -f compose/evals.yaml up --build
```

Temporal infrastructure lives in `temporal.yaml`, the MCP server and answer
workers in `mcp.yaml`, and eval workers in `evals.yaml`. All use the same default
Compose project and network because their files live in `compose/`. If using
`-p`, supply the same name in every terminal. Use Ctrl+C or `stop` to stop one
stack independently; avoid `--remove-orphans`, since the other stacks share
the project. The eval CLI submits directly to Temporal; MCP exposes
`run_evals` and `get_evals` for starting and polling the same eval workflow.
See the
[MCP](apps/mcp/README.md) and [eval](apps/evals/README.md) READMEs for commands.

## Checks

Python 3.13 or newer and
[uv](https://docs.astral.sh/uv/getting-started/installation/) are required only
for running repository checks directly on the host. Install the locked
environment and Git hooks with `uv sync` and `uv run pre-commit install`.

```bash
uv lock --check
uv run pre-commit run --all-files
uv run ruff check apps backend
uv run ruff format --check apps backend
uv run pytest
```

## Run DB tests

```bash
docker compose -f compose/test.yaml up -d
TEST_DATABASE_URL=postgresql+asyncpg://test:test@localhost:5433/test_db uv run pytest
docker compose -f compose/test.yaml down -v
```
