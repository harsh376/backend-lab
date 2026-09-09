"""Application configuration loaded from environment variables."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    db_host: str | None = None
    db_port: str = "5432"
    db_name: str = "my_db"
    db_user: str = "postgres"
    db_password: str = "postgres"

    otel_service_name: str = "title-api"
    otel_exporter_otlp_endpoint: str | None = None
    otel_exporter_otlp_traces_endpoint: str | None = None
    otel_exporter_otlp_metrics_endpoint: str | None = None

    @property
    def database_url(self) -> str | None:
        """Postgres DSN, or None to fall back to the in-memory repository."""
        if not self.db_host:
            return None
        return (
            f"postgresql+asyncpg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def trace_otlp_enabled(self) -> bool:
        return bool(
            self.otel_exporter_otlp_endpoint or self.otel_exporter_otlp_traces_endpoint
        )

    @property
    def metric_otlp_enabled(self) -> bool:
        return bool(
            self.otel_exporter_otlp_endpoint or self.otel_exporter_otlp_metrics_endpoint
        )
