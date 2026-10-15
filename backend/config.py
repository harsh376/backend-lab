"""Shared runtime configuration for API, MCP, and background workers."""

from pydantic import PositiveInt, SecretStr

from backend.db.config import DatabaseSettings


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

    langfuse_public_key: str | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_base_url: str = "https://cloud.langfuse.com"
    langfuse_tracing_environment: str = "local"
    langfuse_tracing_enabled: bool = True

    @property
    def otlp_enabled(self) -> bool:
        return self.otel_exporter_otlp_endpoint is not None
