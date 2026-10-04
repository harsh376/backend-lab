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

The Terraform setup runs locally and stores remote state in a private,
versioned S3 bucket with native state locking. Run `bin/terraform.sh help` for the
state-bucket setup and development-environment workflow.

The runtime request path is:

```text
API → Service → Repository → PostgreSQL
```

Repository contracts are structural `Protocol` types. Runtime implementations
persist through SQLAlchemy to PostgreSQL.

## Quick start

Docker with the Compose plugin is required to run the application.

```bash
docker compose -f compose/base.yaml up --build
```

Compose starts PostgreSQL, applies migrations, starts the API and React frontend,
and starts the local observability stack. The frontend is available at
<http://localhost:5173> with hot reload for source edits.

### Sample requests

```bash
# Check that the process is running and its dependencies are ready.
curl -i 'http://127.0.0.1:8000/health/live'
curl -i 'http://127.0.0.1:8000/health/ready'

# Create a title.
curl -i -X POST 'http://127.0.0.1:8000/v1/titles' \
  -H 'Content-Type: application/json' \
  -d '{"id":"movie-456","name":"Another Movie","description":"An example title."}'

# Retrieve the title that was just created.
curl -i 'http://127.0.0.1:8000/v1/titles/movie-456'
```

Interactive API documentation is available at <http://127.0.0.1:8000/docs>.

### React frontend

The Vite + React + TypeScript app lives in `apps/frontend`:

```bash
cd apps/frontend
npm ci
npm run dev
```

See [the frontend README](apps/frontend/README.md) for requirements, checks, and
the development proxy for connecting to FastAPI.

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

### Alembic migrations

With PostgreSQL running, generate a migration from changes to the SQLAlchemy
models, inspect the database's currently applied migration, and apply all
available migrations with:

```bash
uv run alembic -c apps/api/alembic.ini revision --autogenerate -m "describe change"
uv run alembic -c apps/api/alembic.ini current
uv run alembic -c apps/api/alembic.ini upgrade head
```

Run `uv run alembic -c apps/api/alembic.ini heads` to see the newest migration
available in the repository. Alembic uses the local PostgreSQL defaults from
`apps/api/alembic.ini`; set the `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, and
`DB_PASSWORD` environment variables to target a different database.

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

Grafana provisions the version-controlled `API — HTTP Overview` and
`Application` dashboards in its `API` folder from `infra/grafana`. The HTTP
dashboard covers request rate, client and server error percentage, active
requests, latency percentiles, status-code rates, and a latency heatmap. The
application dashboard covers title operation rates, outcomes, success
percentage, and repository failures. Grafana polls the dashboard files for
changes every 30 seconds; restart the `otel-lgtm` service after changing the
provider configuration itself.

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
SQLite by default, so the SQLAlchemy implementation is exercised without
requiring Docker. The same tests can also run against real PostgreSQL:

```bash
docker compose -f compose/test.yaml up -d
TEST_DATABASE_URL=postgresql+asyncpg://test:test@localhost:5433/test_db uv run pytest
docker compose -f compose/test.yaml down -v
```

`compose/test.yaml` starts an isolated, disk-backed-in-tmpfs PostgreSQL
instance under its own Compose project (`my-app-test`) on port `5433`, so it
never collides with the `compose/base.yaml` dev stack. Each repository test
fixture drops and recreates the schema before running, so tests stay isolated
whichever backend is selected. A production project should additionally run
this PostgreSQL variant in CI.


# Steps to creating a new API

## Phase 1: Complete the API behavior

Request model → Router → ORM model → Database → ORM model → Router → Response model

- Define request and response models next to the router
- Use ORM models directly; do not import or create domain models in this phase
- Deliver the endpoint's functional requirements end to end
- Validate requests and authorization context
- Map expected errors and exceptions to stable response codes
- Log errors and exceptions with structured context
- Test successful and failure paths

## Phase 2: Integrate observability

- Add metrics to `OpenTelemetryMetrics` and record in api handler
- Export logs, metrics, and traces to the OTEL-LGTM stack
- Verify telemetry in Grafana

## Phase 3: Extract business logic

Request model → Router → Service → ORM model → Database → ORM model → Service → Domain model → Router → Response model

- Introduce domain models when the service layer needs representations that are
  independent of HTTP schemas and persistence models

## Phase 4: Extract persistence

Request model → Router → Service → Repository → ORM model → Database → ORM model → Repository → Domain model → Service → Router → Response model

# To do

The topics are ordered by learning priority. After the performance baseline is
in place, every infrastructure phase should follow the same loop:

```text
Baseline → make one change → repeat the workload → explain the result
```

1. Python async programming
   - Event loop, coroutines, and tasks
   - `asyncio` and AnyIO
   - Structured concurrency using `TaskGroup`
   - Cancellation, deadlines, and timeouts
   - Bounded concurrency and backpressure
   - Async queues and synchronization primitives
   - Async generators, iterators, and context managers
   - Thread pools for blocking I/O
   - Process pools for CPU-bound work
   - Concurrency versus parallelism

2. Performance engineering using Locust and OTEL-LGTM
   - Model realistic API workloads and seed deterministic test data
   - Establish PostgreSQL-only latency, throughput, and resource baselines
   - Run load, stress, spike, and soak tests
   - Track request rate, errors, and p50/p95/p99 latency in Locust
   - Export application metrics, logs, and traces using OpenTelemetry
   - Collect container CPU, memory, network, and throttling metrics using
     cAdvisor
   - Collect PostgreSQL and later dependency metrics using OpenTelemetry
     receivers or Prometheus exporters
   - Visualize application and resource saturation in Grafana
   - Record the commit, workload, dataset, configuration, and run time for each
     experiment

3. Caching using Redis
   - Cache-aside reads
   - TTL and TTL jitter
   - Cache invalidation
   - Negative caching
   - Stampede protection and single-flight request coalescing
   - Versioned keys
   - Eviction policies, including approximate LRU
   - Pre-warming
   - Redis failure behavior
   - Sharding
   - Compare cold-cache, warm-cache, expiration, and unavailable-cache
     workloads

4. Messaging foundations using SQS and SNS
   - At-least-once delivery
   - Standard versus FIFO queues
   - Visibility timeout and extension
   - Idempotent handlers
   - Retries with exponential backoff and jitter
   - Poison messages and DLQs
   - Long polling and batching
   - Partial batch failures
   - SNS-to-SQS pub/sub and fan-out
   - Transactional outbox pattern
   - Measure enqueue latency, queue depth, oldest-message age, processing
     throughput, retries, and duplicate effects

5. Event streaming using Kafka
   - Topics, partitions, offsets, and ordering
   - Consumer groups and rebalancing
   - Key selection and partition skew
   - At-least-once processing
   - Idempotent consumers
   - Consumer lag and backpressure
   - Batching and throughput-versus-latency tradeoffs
   - Retry topics and DLQs
   - Retention and compaction
   - Producer acknowledgements and idempotence
   - Schema evolution
   - Exactly-once processing and its transactional boundaries
   - Compare Kafka pub/sub with SNS and Redis pub/sub

6. Search using Elasticsearch
   - Mappings and field types
   - Indexing and bulk indexing
   - Exact filters versus full-text search
   - Analyzers and tokenization
   - Relevance and scoring
   - Aggregations and faceted search
   - Auto-complete and auto-suggest
   - Pagination
   - Index aliases and zero-downtime reindexing
   - CDC or outbox-driven PostgreSQL synchronization
   - Stale-result and failure behavior
   - Sharding, replication, and segments
   - Nested and parent-child modeling
   - Geospatial queries

7. Inter-service communication using gRPC
   - Protobuf contracts and compatibility
   - Deadlines and cancellation
   - Retries and idempotency
   - Streaming
   - Load balancing and observability

8. Real-time delivery
   - Server-sent events
   - WebSockets
   - Connection lifecycle and backpressure
   - Reconnection and missed-event handling
   - Connection-count and message-rate load tests

9. Durable workflows using Temporal
   - Workflows versus activities
   - Retries, timeouts, heartbeats, and cancellation
   - Durable timers
   - Determinism and workflow versioning
   - Signals, queries, and updates
   - Compensation and sagas
   - End-to-end workflow latency and backlog measurements


- [ ] Timestamped key-value store
- [x] LRU cache
- In-memory file system
- The prompt was about a book/library management system where users felt the frontend table was too long and hard to use. After chatting with the AI PM, I figured out that the requested feature involved adding two dropdowns and a text input for search/filtering. search/filter UI for the library/book management system. The PM had also mentioned that full unit test and integration test coverage was expected.
-  The feature involved a notification system in the library management app. The requirements included both frontend and backend changes, idempotency, and full test coverage.
- https://www.interviewdb.io/question/instacart
- https://github.com/liquidslr/leetcode-company-wise-problems/blob/main/Instacart/5.%20All.csv
- Leetcode
  - Travelling salesman
  - Knapsack
- For CodeSignal it was implementing a cache key store with timestamps. Started with basic setting and getting, then evolved into more advanced code. 4 different parts. Writing a lot of code for this. For the LLM interview you work with a company called Karat. You are giving an VS code like workspace and an ai to help. You have 50 minutes. They then dump a large project in your space. For me it was a bus route simulator. I was then asked to implement a feature : Have the system prioritize Priority Pass people. I used the LLM to track down the code and implement it, but it was difficult to test in code that is unknown to me. The next feature was implementing wheelchairs for the bus which requires special capacity checks.
- https://www.reddit.com/r/InterviewDB/comments/1uduryw/instacart_fullstack_engineer_assessment_on/
- https://www.reddit.com/r/OfferEngineering/comments/1wpecgm/instacart_software_engineer_swe_oa_onsite/
- https://www.jointaro.com/interviews/questions/average-waiting-time/?company=instacart
- https://www.jointaro.com/interviews/questions/find-first-and-last-position-of-element-in-sorted-array/?company=instacart

## Celery background workers

The base Compose stack also runs Redis and an `api-worker` service using the
same image as the API. The API publishes JSON tasks to the `api` queue; workers
execute them independently. Redis uses append-only persistence and a named
volume, with eviction disabled. No task result backend or scheduler is enabled.

```bash
docker compose -f compose/base.yaml up -d --build
curl -X POST http://localhost:8000/v1/background/ping
docker compose -f compose/base.yaml logs -f api-worker
```

The smoke-test endpoint returns HTTP 202 with a task ID after enqueueing; look
for `background_ping_completed` and the request ID in worker logs. HTTP 202
means accepted, not completed. Broker connection failures return HTTP 503.
There is no task-status polling endpoint. Worker application logs are also
exported to OTEL-LGTM under `api-worker`.

Set `CELERY_BROKER_URL` for both API and worker deployments. Compose defaults
to `redis://redis:6379/0`; host Python processes default to
`redis://localhost:6379/0`. Redis's local port is bound to loopback. Configure
worker concurrency with `CELERY_WORKER_CONCURRENCY` (default 2). Workers have
60-second soft and 75-second hard task limits and 90 seconds for graceful
container shutdown; review these limits when introducing real workloads.

Define tasks in `apps/api/background/tasks.py`. Pass IDs or JSON values, and create any
database sessions inside the worker task, never from the API request. The ping
task uses normal early acknowledgment; durable business jobs need explicit
idempotency, retry, and acknowledgment policies. Database writes and publishing
are not atomic; use an outbox when a committed change must reliably enqueue work.

In production, deploy the API and workers separately and point both at a private
Redis service with appropriate authentication/TLS. Use a separate Redis instance
for caching so cache eviction and memory usage cannot affect queued jobs.
