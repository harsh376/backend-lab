# Backend systems learning project

Monorepo structure:

- FastAPI app: `apps/api/`
- MCP server: `apps/mcp/`
- React frontend: `apps/frontend/`
- Pure JS frontend: `apps/basic_frontend/`
- Python concepts: `apps/concepts/`
- Shared backend code (DB, Service-Repository-Domain, Observability): `backend/`
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
