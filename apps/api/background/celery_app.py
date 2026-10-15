"""Celery entry point shared by API producers and independent workers."""

from celery import Celery
from celery.signals import worker_process_init, worker_process_shutdown

from backend.config import Settings
from backend.observability.logging import configure_logger
from backend.observability.telemetry import Telemetry, configure_telemetry

settings = Settings()
celery_app = Celery(
    "api", broker=settings.celery_broker_url, include=["apps.api.background.tasks"]
)
celery_app.conf.update(
    beat_schedule={
        "create-hold-notifications": {
            "task": "api.create_hold_notifications",
            "schedule": float(settings.hold_notification_interval_seconds),
        },
    },
    task_default_queue="api",
    task_serializer="json",
    accept_content=["json"],
    task_ignore_result=True,
    timezone="UTC",
    broker_connection_retry_on_startup=True,
    broker_connection_timeout=3,
    broker_transport_options={"socket_connect_timeout": 3, "socket_timeout": 3},
    task_publish_retry=False,
    worker_prefetch_multiplier=1,
    worker_redirect_stdouts=False,
    task_soft_time_limit=60,
    task_time_limit=75,
)

_telemetry: Telemetry | None = None


@worker_process_init.connect
def initialize_worker(**kwargs: object) -> None:
    """Create exporter threads after the worker forks."""
    global _telemetry
    _telemetry = configure_telemetry(
        service_name=settings.otel_service_name,
        endpoint=settings.otel_exporter_otlp_endpoint,
        metric_export_interval=settings.otel_metric_export_interval,
    )
    configure_logger("api-worker", _telemetry.logger_provider)


@worker_process_shutdown.connect
def shutdown_worker(**kwargs: object) -> None:
    if _telemetry is not None:
        _telemetry.shutdown()
