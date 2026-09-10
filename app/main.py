"""Application composition root selected by DB_HOST."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.application import create_app
from app.api.dependencies import ApplicationDependencies, ReadinessProbe
from app.config import Settings
from app.db.repository import (
    InMemoryTitleRepository,
    PostgresTitleRepository,
    TitleRepository,
)
from app.db.session import Database
from app.domain import Title
from app.observability.logging import configure_logger
from app.observability.metrics import OpenTelemetryMetrics
from app.observability.telemetry import configure_telemetry
from app.service import TitleService

settings = Settings()
telemetry = configure_telemetry(settings)
logger = configure_logger(settings.otel_service_name, telemetry.logger_provider)
metrics = OpenTelemetryMetrics(telemetry.meter_provider)
database: Database | None = None
repository: TitleRepository
readiness_probe: ReadinessProbe | None

if settings.database_url:
    database = Database(settings.database_url)
    repository = PostgresTitleRepository(database.sessions)
    readiness_probe = database.is_ready
else:
    repository = InMemoryTitleRepository(
        [
            Title(
                id="movie-123",
                name="Example Movie",
                description="Sample data used when PostgreSQL is not configured.",
            )
        ]
    )
    readiness_probe = None

service = TitleService(repository, metrics, logger)
dependencies = ApplicationDependencies(
    service=service,
    logger=logger,
    readiness_probe=readiness_probe,
)
app = create_app(
    dependencies,
    tracer_provider=telemetry.tracer_provider,
    meter_provider=telemetry.meter_provider,
)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    try:
        yield
    finally:
        if database is not None:
            await database.close()
        telemetry.shutdown()


app.router.lifespan_context = lifespan
