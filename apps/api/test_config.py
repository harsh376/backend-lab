"""Tests for environment-driven application settings."""

from apps.api.config import Settings

_ENV_VARS = (
    "DB_HOST",
    "DB_PORT",
    "DB_NAME",
    "DB_USER",
    "DB_PASSWORD",
    "OTEL_SERVICE_NAME",
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "OTEL_METRIC_EXPORT_INTERVAL",
)


def _clear_env(monkeypatch) -> None:
    for name in _ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def test_defaults_when_unset(monkeypatch) -> None:
    _clear_env(monkeypatch)

    settings = Settings(_env_file=None)

    assert settings.database_url is None
    assert settings.otel_service_name == "api"
    assert settings.otlp_enabled is False
    assert settings.otel_metric_export_interval == 60_000


def test_reads_environment_variables(monkeypatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("DB_HOST", "host")
    monkeypatch.setenv("DB_PORT", "6543")
    monkeypatch.setenv("DB_NAME", "db")
    monkeypatch.setenv("DB_USER", "u")
    monkeypatch.setenv("DB_PASSWORD", "p")
    monkeypatch.setenv("OTEL_SERVICE_NAME", "custom-service")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4317")
    monkeypatch.setenv("OTEL_METRIC_EXPORT_INTERVAL", "20000")

    settings = Settings(_env_file=None)

    assert settings.database_url == "postgresql+asyncpg://u:p@host:6543/db"
    assert settings.otel_service_name == "custom-service"
    assert settings.otlp_enabled is True
    assert settings.otel_exporter_otlp_endpoint == "http://collector:4317"
    assert settings.otel_metric_export_interval == 20_000
