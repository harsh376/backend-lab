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


# Celery background workers

```bash
docker compose -f compose/base.yaml up -d --build

curl -X POST http://localhost:8000/v1/background/ping

docker compose -f compose/base.yaml logs -f api-worker
```
