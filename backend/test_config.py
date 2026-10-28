"""Tests for environment-driven application settings."""

import pytest
from pydantic import ValidationError

from backend.config import Settings

_ENV_VARS = (
    "TIMEOUT_MODEL_REQUEST_SECONDS",
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
@pytest.mark.parametrize("field", ["eval_judge_model", "mcp_verifier_model"])
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
    assert settings.timeout_model_request_seconds == 180


@pytest.mark.parametrize("seconds", [25, 180])
def test_model_timeout_environment_override(monkeypatch, seconds):
    monkeypatch.setenv("TIMEOUT_MODEL_REQUEST_SECONDS", str(seconds))
    assert Settings(_env_file=None).timeout_model_request_seconds == seconds


@pytest.mark.parametrize("seconds", [0, 181, float("inf"), float("nan")])
def test_model_timeout_cannot_exceed_activity_ceiling(monkeypatch, seconds):
    monkeypatch.setenv("TIMEOUT_MODEL_REQUEST_SECONDS", str(seconds))
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_timeout_snapshot_ignores_later_environment_changes(monkeypatch):
    settings = Settings(
        timeout_model_request_seconds=150,
        timeout_model_request_max_seconds=240,
        timeout_activity_overhead_seconds=45,
        timeout_answer_eval_seconds=900,
        openai_api_key="must-not-be-recorded",
    )
    snapshot = settings.timeout_snapshot()
    monkeypatch.setenv("TIMEOUT_MODEL_REQUEST_SECONDS", "20")
    monkeypatch.setenv("TIMEOUT_MODEL_REQUEST_MAX_SECONDS", "30")
    monkeypatch.setenv("TIMEOUT_ANSWER_EVAL_SECONDS", "120")
    restored = Settings.from_timeout_snapshot(snapshot)
    assert restored.timeout_snapshot() == snapshot
    assert restored.timeout_model_activity_seconds == 285
    assert restored.timeout_model_activity_total_seconds == 900
    assert restored.timeout_eval_scoring_seconds == 285
    assert "openai_api_key" not in snapshot
    assert "must-not-be-recorded" not in str(snapshot)


def test_legacy_workflow_timeouts_do_not_depend_on_environment(monkeypatch):
    monkeypatch.setenv("TIMEOUT_MODEL_REQUEST_SECONDS", "10")
    monkeypatch.setenv("TIMEOUT_ANSWER_EVAL_SECONDS", "30")
    restored = Settings.from_timeout_snapshot(None)
    assert restored.timeout_model_request_seconds == 180
    assert restored.timeout_answer_eval_seconds == 600


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
