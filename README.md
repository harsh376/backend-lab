# Backend systems learning project

A FastAPI project for learning backend architecture and infrastructure. The
example domain is intentionally simple: create and retrieve titles, leaving room
to focus on persistence, observability, messaging, workflows, agents, and
operations.

## Structure

The repository is a single Python project organized as a monorepo. Deployable
applications live in `apps`, while reusable technical infrastructure lives in
`shared`. Business models and persistence remain inside the application that
owns them. Tests live beside the files they cover as `test_{file_name}.py` and
are omitted from this diagram for clarity.

```text
apps/
└── api/
    ├── main.py                   Application composition root
    ├── config.py                 Environment-driven settings
    ├── application.py            FastAPI application factory
    ├── dependencies.py           FastAPI dependency providers
    ├── middleware.py             Request ID propagation
    ├── schemas.py                HTTP error schemas
    ├── domain.py                 Title domain model
    ├── service.py                Title use-case orchestration
    ├── metrics.py                Title-specific OpenTelemetry metrics
    ├── Dockerfile                API container image
    ├── alembic.ini               Database migration configuration
    ├── routers/                  Health and title endpoints
    └── db/
        ├── models.py             Title SQLAlchemy model
        ├── repository.py         Repository contract and implementations
        └── migrations/           API-owned schema history

shared/
├── database/
│   └── session.py                Engine, sessions, and database health
└── observability/
    ├── logging.py                Structured logging
    └── telemetry.py              OTel providers and OTLP exporters

infra/                             Infrastructure configuration
├── grafana/                       Provisioned Grafana dashboards
└── terraform/                     AWS state-bucket script and environment roots

compose/base.yaml                   Base stack: DB, migrations, API, OTEL-LGTM
pyproject.toml                      Python project and tool configuration
uv.lock                             Reproducible dependency lockfile
.pre-commit-config.yaml             Automated repository checks
```

The Terraform setup runs locally and stores remote state in a private,
versioned S3 bucket with native state locking. See
[`infra/terraform/README.md`](infra/terraform/README.md) for the state-bucket
setup and development-environment workflow.

The runtime request path is:

```text
API → Service → TitleRepository → In-memory storage or PostgreSQL
```

`TitleRepository` is a structural `Protocol`. The two implementations satisfy
the contract without inheriting from it.

## Quick start

Docker with the Compose plugin is required to run the application.

```bash
docker compose -f compose/base.yaml up --build
```

Compose starts PostgreSQL, applies migrations, starts the API, and starts the
local observability stack. The API uses an in-memory repository only in tests
that explicitly construct it that way.

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
application logs are correlated with the active trace. Compose configures the
API to export all three signals to the bundled OTLP/gRPC collector.

The configured endpoint is shared by the trace, metric, and log exporters.
Settings are read from the process environment. When no endpoint is configured,
instrumentation and JSON stdout logging remain enabled but no exporter worker
is started.

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

PostgreSQL runs through Compose. The full stack automatically waits for it to
become healthy and applies the API migrations before starting the API. To start
only PostgreSQL:

```bash
docker compose -f compose/base.yaml up -d postgres
```

## Docker

`docker compose -f compose/base.yaml up --build` runs the full stack:
PostgreSQL, a one-shot `migrations` service that runs `alembic upgrade head`
against it, the API (built from `apps/api/Dockerfile`), and Grafana OTEL-LGTM. The
API exports traces, metrics, and logs to OTEL-LGTM's bundled OpenTelemetry
Collector and waits for migrations to finish before starting.

```bash
docker compose -f compose/base.yaml up --build
curl -i http://localhost:8000/v1/titles/movie-123
```

Additional Compose stacks should layer their overrides after the base file:

```bash
docker compose -f compose/base.yaml \
  -f compose/override.yaml \
  up --build
```

Compose automatically loads `compose/.env`. Copy `compose/.env.example` when
setting up a new checkout or when you want to restore the documented defaults.

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

Python 3.13 or newer and
[uv](https://docs.astral.sh/uv/getting-started/installation/) are required only
for running repository checks directly on the host. Install the locked
environment and Git hooks with `uv sync` and `uv run pre-commit install`.

```bash
uv lock --check
uv run pre-commit run --all-files
uv run ruff check apps shared
uv run ruff format --check apps shared
uv run pytest
uv run alembic -c apps/api/alembic.ini upgrade head --sql
```

The repository tests are colocated with their implementation and use async
SQLite, so the SQLAlchemy implementation is exercised without requiring Docker.
A production project should additionally run the same repository contract tests
against PostgreSQL in CI.
