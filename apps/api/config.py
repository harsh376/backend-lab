"""Application configuration loaded from environment variables."""

from pydantic import PositiveInt

from shared.database.config import DatabaseSettings


class Settings(DatabaseSettings):
    hold_reminder_window_minutes: PositiveInt = 120
    hold_notification_interval_seconds: PositiveInt = 600
    hold_notification_batch_size: PositiveInt = 200

    temporal_address: str = "localhost:7233"
    elasticsearch_url: str = "http://localhost:9200"
    kilt_index: str = "kilt"

    celery_broker_url: str = "redis://localhost:6379/0"

    otel_service_name: str = "api"
    otel_exporter_otlp_endpoint: str | None = None
    otel_metric_export_interval: PositiveInt = 60000

    @property
    def otlp_enabled(self) -> bool:
        return self.otel_exporter_otlp_endpoint is not None
