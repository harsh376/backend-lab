## PostgreSQL

PostgreSQL runs through Compose. The full stack automatically waits for it to
become healthy and applies the API migrations before starting the API. To start
only PostgreSQL:

```bash
docker compose -f compose/base.yaml up -d postgres
```

### Alembic migrations

With PostgreSQL running, generate a migration from changes to the SQLAlchemy
models, inspect the database's currently applied migration, and apply all
available migrations with:

```bash
uv run alembic -c backend/alembic.ini revision --autogenerate -m "describe change"
uv run alembic -c backend/alembic.ini current
uv run alembic -c backend/alembic.ini upgrade head
```

Run `uv run alembic -c backend/alembic.ini heads` to see the newest migration
available in the repository. Alembic uses the local PostgreSQL defaults from
`backend/alembic.ini`; set the `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, and
`DB_PASSWORD` environment variables to target a different database.
