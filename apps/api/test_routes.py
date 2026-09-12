import logging

import pytest
from httpx import ASGITransport, AsyncClient
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from apps.api.application import create_app
from apps.api.db.repository import (
    InMemoryTitleRepository,
    RepositoryUnavailableError,
)
from apps.api.dependencies import ApplicationDependencies
from apps.api.domain import Title
from apps.api.metrics import OpenTelemetryMetrics
from apps.api.service import TitleService


class UnavailableRepository:
    async def get_by_id(self, title_id: str) -> Title:
        raise RepositoryUnavailableError("database unavailable")

    async def create(self, title: Title) -> Title:
        raise RepositoryUnavailableError("database unavailable")


def make_app(repository=None, readiness_probe=None):
    repository = repository or InMemoryTitleRepository(
        [Title(id="movie-123", name="Example Movie")]
    )
    metrics = OpenTelemetryMetrics()
    logger = logging.getLogger(f"test-{id(metrics)}")
    logger.addHandler(logging.NullHandler())
    service = TitleService(repository, metrics, logger)
    dependencies = ApplicationDependencies(
        service=service,
        logger=logger,
        readiness_probe=readiness_probe,
    )
    return create_app(dependencies)


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=make_app()),
        base_url="http://test",
    ) as value:
        yield value


async def test_get_title(client: AsyncClient) -> None:
    response = await client.get(
        "/v1/titles/movie-123",
        headers={"X-Request-ID": "request-123"},
    )
    assert response.status_code == 200
    assert response.json() == {
        "id": "movie-123",
        "name": "Example Movie",
        "description": None,
    }
    assert response.headers["X-Request-ID"] == "request-123"


async def test_create_title(client: AsyncClient) -> None:
    response = await client.post(
        "/v1/titles",
        json={
            "id": "movie-456",
            "name": "Another Movie",
            "description": "Created through the API.",
        },
    )
    assert response.status_code == 201
    assert response.json()["id"] == "movie-456"


async def test_duplicate_title_returns_409(client: AsyncClient) -> None:
    response = await client.post(
        "/v1/titles",
        json={"id": "movie-123", "name": "Duplicate"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "TITLE_ALREADY_EXISTS"


async def test_missing_title_returns_404(client: AsyncClient) -> None:
    response = await client.get("/v1/titles/missing")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "TITLE_NOT_FOUND"


async def test_invalid_title_returns_400(client: AsyncClient) -> None:
    response = await client.post(
        "/v1/titles",
        json={"id": "movie-456", "name": ""},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_ARGUMENT"


async def test_repository_failure_returns_503() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=make_app(UnavailableRepository())),
        base_url="http://test",
    ) as client:
        response = await client.get("/v1/titles/movie-123")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"


async def test_health_endpoints(client: AsyncClient) -> None:
    liveness_response = await client.get("/health/live")
    readiness_response = await client.get("/health/ready")

    assert liveness_response.status_code == 200
    assert liveness_response.json() == {"status": "ok"}
    assert readiness_response.status_code == 200
    assert readiness_response.json() == {"status": "ready"}


async def test_readiness_reports_an_unavailable_dependency() -> None:
    async def unavailable() -> bool:
        return False

    async with AsyncClient(
        transport=ASGITransport(app=make_app(readiness_probe=unavailable)),
        base_url="http://test",
    ) as client:
        response = await client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}


async def test_otel_fastapi_instrumentation_emits_trace_and_metric() -> None:
    span_exporter = InMemorySpanExporter()
    tracer_provider = TracerProvider()
    tracer_provider.add_span_processor(SimpleSpanProcessor(span_exporter))
    metric_reader = InMemoryMetricReader()
    meter_provider = MeterProvider(metric_readers=[metric_reader])

    repository = InMemoryTitleRepository([Title(id="movie-123", name="Example Movie")])
    application_metrics = OpenTelemetryMetrics(meter_provider)
    logger = logging.getLogger("test-otel-instrumentation")
    service = TitleService(repository, application_metrics, logger)
    dependencies = ApplicationDependencies(service=service, logger=logger)
    app = create_app(
        dependencies,
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/v1/titles/movie-123",
            headers={"X-Request-ID": "request-otel-123"},
        )

    assert response.status_code == 200
    server_span = next(
        span
        for span in span_exporter.get_finished_spans()
        if span.name == "GET /v1/titles/{title_id}"
    )
    assert server_span.attributes["app.request.id"] == "request-otel-123"
    metric_names = {
        metric.name
        for resource_metrics in metric_reader.get_metrics_data().resource_metrics
        for scope_metrics in resource_metrics.scope_metrics
        for metric in scope_metrics.metrics
    }
    assert "http.server.request.duration" in metric_names
    tracer_provider.shutdown()
    meter_provider.shutdown()
