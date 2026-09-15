"""Application composition root selected by DB_HOST."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from apps.api.application import create_app
from apps.api.config import Settings
from apps.api.dependencies import ApplicationDependencies
from apps.api.metrics import OpenTelemetryMetrics
from apps.api.repositories.title import PostgresTitleRepository
from apps.api.repositories.user_list import PostgresUserListRepository
from apps.api.services.title import TitleService
from apps.api.services.user_list import UserListService
from shared.database.session import Database
from shared.observability.logging import configure_logger
from shared.observability.telemetry import configure_telemetry

settings = Settings()
telemetry = configure_telemetry(
    service_name=settings.otel_service_name,
    endpoint=settings.otel_exporter_otlp_endpoint,
    metric_export_interval=settings.otel_metric_export_interval,
)
logger = configure_logger(settings.otel_service_name, telemetry.logger_provider)
metrics = OpenTelemetryMetrics(telemetry.meter_provider)
database = Database(settings.database_url)
repository = PostgresTitleRepository(database.sessions)
user_list_repository = PostgresUserListRepository(database.sessions)
service = TitleService(repository, metrics, logger)
user_list_service = UserListService(user_list_repository, logger)
dependencies = ApplicationDependencies(
    service=service,
    user_list_service=user_list_service,
    logger=logger,
    metrics=metrics,
    database_sessions=database.sessions,
    readiness_probe=database.is_ready,
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
        await database.close()
        telemetry.shutdown()


app.router.lifespan_context = lifespan
