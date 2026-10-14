"""Application composition root selected by DB_HOST."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from apps.api.application import create_app
from apps.api.background.celery_app import celery_app
from apps.api.config import Settings
from apps.api.dependencies import ApplicationDependencies
from backend.db.session import Database
from backend.metrics import OpenTelemetryMetrics
from backend.observability.logging import configure_logger
from backend.observability.telemetry import configure_telemetry
from backend.repositories.title import PostgresTitleRepository
from backend.repositories.user_list import PostgresUserListRepository
from backend.services.item_reservation.item_reservation import ItemReservation
from backend.services.title import TitleService
from backend.services.user_list import UserListService

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
    task_queue=celery_app,
    item_reservation_service=ItemReservation(database.sessions),
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
        celery_app.close()
        await database.close()
        telemetry.shutdown()


app.router.lifespan_context = lifespan
