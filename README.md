# Backend systems learning project

A FastAPI project for learning backend architecture and infrastructure. The
example domain is intentionally simple: create and retrieve titles, leaving room
to focus on persistence, observability, messaging, workflows, agents, and
operations.

## Structure

The repository starts as a modular monolith. Tests live beside the files they
cover as `test_{file_name}.py`; they are omitted from this diagram for clarity.
Folders are added only when their corresponding capability is implemented.

```text
app/
├── __init__.py
├── main.py                       Application composition root
├── config.py                     Environment-driven settings (pydantic-settings)
├── domain.py                     Domain models
├── service.py                    Use-case orchestration
├── Dockerfile                    API container image
├── alembic.ini                   Database migration configuration
│
├── api/
│   ├── __init__.py
│   ├── application.py            FastAPI application factory
│   ├── schemas.py                HTTP request and response schemas
│   └── middleware.py             Request ID propagation
│
├── db/
│   ├── __init__.py
│   ├── models.py                 SQLAlchemy persistence models
│   ├── repository.py             Repository contracts and implementations
│   └── session.py                Engine, sessions, and database health
│
├── observability/
│   ├── __init__.py
│   ├── logging.py                Structured logging
│   ├── metrics.py                OpenTelemetry domain metrics
│   └── telemetry.py              OTel providers and OTLP exporters
│
├── cache/                         Redis client caching (planned)
├── messaging/                     Streams, queues, and pub-sub (planned)
├── workflows/                     Durable sagas and compensations (planned)
├── workers/                       Background worker pipelines (planned)
├── search/                        CDC-backed Elasticsearch indexing (planned)
└── agents/                        Agents, tools, and colocated evals (planned)
    └── evals/

migrations/                        Alembic schema history

infra/                             Infrastructure configuration
├── grafana/                       Provisioned Grafana dashboards
├── terraform/                     Terraform modules and environments (planned)
└── cdc/                           CDC source and Elasticsearch sink configuration (planned)

compose.yaml                        Local stack: DB, migrations, API, OTEL-LGTM
pyproject.toml                      Python project and tool configuration
uv.lock                             Reproducible dependency lockfile
.pre-commit-config.yaml             Automated repository checks
```

Entries marked `planned` describe intended additions. Their files and
directories are deliberately absent until the corresponding capability exists.

The runtime request path is:

```text
API → Service → TitleRepository → In-memory storage or PostgreSQL
```

`TitleRepository` is a structural `Protocol`. The two implementations satisfy
the contract without inheriting from it.

## Quick start

Python 3.13 or newer and
[uv](https://docs.astral.sh/uv/getting-started/installation/) are required.

```bash
uv sync
uv run pre-commit install
uv run uvicorn app.main:app --reload
```

`uv sync` creates `.venv`, installs the application dependencies and development
tools, and uses the committed `uv.lock` file. The project is intentionally not
installed as a distributable Python package. The pre-commit install command
enables the configured checks for future commits.

Without `DB_HOST`, the application uses an in-memory repository with one
sample title.

```bash
curl -i 'http://127.0.0.1:8000/v1/titles/movie-123'

curl -i -X POST 'http://127.0.0.1:8000/v1/titles' \
  -H 'Content-Type: application/json' \
  -d '{"id":"movie-456","name":"Another Movie"}'
```

Interactive API documentation is available at <http://127.0.0.1:8000/docs>.

## OpenTelemetry

FastAPI HTTP traces and metrics are produced by the standard OpenTelemetry
instrumentation. Domain metrics use the OpenTelemetry metrics API as well, and
application logs are correlated with the active trace. Set an OTLP/gRPC
collector endpoint to export all three signals:

```bash
export OTEL_SERVICE_NAME=api
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
export OTEL_SEMCONV_STABILITY_OPT_IN=http
uv run uvicorn app.main:app --reload
```

The configured endpoint is shared by the trace, metric, and log exporters.
Values loaded from `.env` are passed directly to the exporters. When no
endpoint is configured, instrumentation and JSON stdout logging remain enabled
but no exporter worker is started.

The `http` semantic-convention setting emits only stable HTTP telemetry. The
provisioned dashboard uses the `http.server.request.duration` metric and its
`http.route`, `http.request.method`, and `http.response.status_code`
attributes.

The Docker Compose stack includes
[Grafana OTEL-LGTM](https://grafana.com/docs/opentelemetry/docker-lgtm/), a
development OpenTelemetry backend containing an OpenTelemetry Collector,
Prometheus, Tempo, Loki, Pyroscope, and Grafana. It receives OTLP/gRPC on
`4317`, OTLP/HTTP on `4318`, persists telemetry in a Docker volume, and exposes
Grafana at <http://localhost:3000>.

## PostgreSQL

```bash
docker compose up -d postgres
export DB_HOST=localhost
uv run alembic -c app/alembic.ini upgrade head
uv run uvicorn app.main:app --reload
```

## Docker

`docker compose up --build` runs the full stack:
PostgreSQL, a one-shot `migrations` service that runs `alembic upgrade head`
against it, the API (built from `app/Dockerfile`), and Grafana OTEL-LGTM. The
API exports traces, metrics, and logs to OTEL-LGTM's bundled OpenTelemetry
Collector and waits for migrations to finish before starting.

```bash
docker compose up --build
curl -i http://localhost:8000/v1/titles/movie-123
```

The API is published on <http://localhost:8000>, PostgreSQL on `5432`, Grafana
on <http://localhost:3000>, and OTEL-LGTM's OTLP/gRPC and OTLP/HTTP receivers on
`4317`/`4318`. In Grafana, use Metrics Drilldown or the Prometheus data source
to inspect metrics, and Traces Drilldown or the Tempo data source to inspect
traces. Search for the `api` service after generating API traffic. Metric
exports occur every 20 seconds in the Docker Compose stack, so new metric data
can take up to 20 seconds to appear.

Grafana provisions the version-controlled `API — HTTP Overview` dashboard
from `infra/grafana`. It covers request rate, client and server error percentage,
active requests, latency percentiles, status-code rates, and a latency heatmap.
Grafana polls the dashboard file for changes every 30 seconds; restart the
`otel-lgtm` service after changing the provider configuration itself.

## Checks

```bash
uv lock --check
uv run pre-commit run --all-files
uv run ruff check app migrations
uv run ruff format --check app migrations
uv run pytest
uv run alembic -c app/alembic.ini upgrade head --sql
```

The repository tests are colocated with their implementation and use async
SQLite, so the SQLAlchemy implementation is exercised without requiring Docker.
A production project should additionally run the same repository contract tests
against PostgreSQL in CI.
