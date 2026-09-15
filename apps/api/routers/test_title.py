import logging

from httpx import ASGITransport, AsyncClient
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from apps.api.application import create_app
from apps.api.dependencies import ApplicationDependencies
from apps.api.domains.title import Title
from apps.api.metrics import OpenTelemetryMetrics
from apps.api.repositories import RepositoryUnavailableError
from apps.api.repositories.title import PostgresTitleRepository
from apps.api.repositories.user_list import PostgresUserListRepository
from apps.api.routers.conftest import make_app
from apps.api.services.title import TitleService
from apps.api.services.user_list import UserListService


class UnavailableRepository:
    async def get_by_id(self, title_id: str) -> Title:
        raise RepositoryUnavailableError("database unavailable")

    async def create(self, title: Title) -> Title:
        raise RepositoryUnavailableError("database unavailable")


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


async def test_repository_failure_returns_503(sqlalchemy_sessions) -> None:
    async with AsyncClient(
        transport=ASGITransport(
            app=await make_app(
                sqlalchemy_sessions,
                repository=UnavailableRepository(),
            )
        ),
        base_url="http://test",
    ) as client:
        response = await client.get("/v1/titles/movie-123")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"


async def test_otel_fastapi_instrumentation_emits_trace_and_metric(
    sqlalchemy_sessions,
) -> None:
    span_exporter = InMemorySpanExporter()
    tracer_provider = TracerProvider()
    tracer_provider.add_span_processor(SimpleSpanProcessor(span_exporter))
    metric_reader = InMemoryMetricReader()
    meter_provider = MeterProvider(metric_readers=[metric_reader])

    repository = PostgresTitleRepository(sqlalchemy_sessions)
    await repository.create(Title(id="movie-123", name="Example Movie"))
    application_metrics = OpenTelemetryMetrics(meter_provider)
    logger = logging.getLogger("test-otel-instrumentation")
    service = TitleService(repository, application_metrics, logger)
    user_list_repository = PostgresUserListRepository(sqlalchemy_sessions)
    user_list_service = UserListService(user_list_repository, logger)
    dependencies = ApplicationDependencies(
        service=service,
        user_list_service=user_list_service,
        logger=logger,
        metrics=application_metrics,
        database_sessions=sqlalchemy_sessions,
    )
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
