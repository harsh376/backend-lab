"""Application configuration loaded from environment variables."""

from pydantic import PositiveInt
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    db_host: str = "localhost"
    db_port: str = "5432"
    db_name: str = "my_db"
    db_user: str = "postgres"
    db_password: str = "postgres"
    test_database_url: str = "sqlite+aiosqlite:///:memory:"

    celery_broker_url: str = "redis://localhost:6379/0"

    otel_service_name: str = "api"
    otel_exporter_otlp_endpoint: str | None = None
    otel_metric_export_interval: PositiveInt = 60000

    @property
    def database_url(self) -> str:
        """Build the PostgreSQL DSN from the database settings."""
        return (
            f"postgresql+asyncpg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def otlp_enabled(self) -> bool:
        return self.otel_exporter_otlp_endpoint is not None
