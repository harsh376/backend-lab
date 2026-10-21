"""Tests for environment-driven application settings."""

import pytest

from backend.config import Settings

_ENV_VARS = (
    "TEMPORAL_ADDRESS",
    "ELASTICSEARCH_URL",
    "KILT_INDEX",
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


@pytest.mark.parametrize("override", [None, "", "anthropic/judge"])
@pytest.mark.parametrize("field", ["eval_answer_model", "mcp_verifier_model"])
def test_model_fallback_resolved_in_settings(monkeypatch, override, field):
    monkeypatch.setenv("MCP_ANSWER_MODEL", "ollama_chat/answer")
    monkeypatch.delenv(field.upper(), raising=False)
    if override is not None:
        monkeypatch.setenv(field.upper(), override)
    assert getattr(Settings(_env_file=None), field) == (
        override or "ollama_chat/answer"
    )


def test_defaults_when_unset(monkeypatch) -> None:
    _clear_env(monkeypatch)

    settings = Settings(_env_file=None)

    assert settings.database_url == (
        "postgresql+asyncpg://postgres:postgres@localhost:5432/my_db"
    )
    assert settings.temporal_address == "localhost:7233"
    assert settings.elasticsearch_url == "http://localhost:9200"
    assert settings.kilt_index == "kilt"
    assert settings.otel_service_name == "api"
    assert settings.otlp_enabled is False
    assert settings.otel_metric_export_interval == 60_000


def test_reads_environment_variables(monkeypatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("TEMPORAL_ADDRESS", "temporal:7233")
    monkeypatch.setenv("ELASTICSEARCH_URL", "http://elasticsearch:9200")
    monkeypatch.setenv("KILT_INDEX", "kilt-v1")
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
    assert settings.temporal_address == "temporal:7233"
    assert settings.elasticsearch_url == "http://elasticsearch:9200"
    assert settings.kilt_index == "kilt-v1"
    assert settings.otel_service_name == "custom-service"
    assert settings.otlp_enabled is True
    assert settings.otel_exporter_otlp_endpoint == "http://collector:4317"
    assert settings.otel_metric_export_interval == 20_000
