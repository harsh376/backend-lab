"""Shared runtime configuration for API, MCP, and background workers."""

from typing import Literal

from pydantic import (
    NonNegativeFloat,
    PositiveFloat,
    PositiveInt,
    SecretStr,
    ValidationInfo,
    field_validator,
    model_validator,
)
from pydantic_settings import SettingsConfigDict

from backend.db.config import DatabaseSettings


class Settings(DatabaseSettings):
    model_config = SettingsConfigDict(allow_inf_nan=False)

    # Timeout fields use TIMEOUT_* environment variables (seconds).
    timeout_model_request_seconds: PositiveFloat = 180
    timeout_model_request_max_seconds: PositiveFloat = 180
    timeout_activity_overhead_seconds: PositiveFloat = 30
    model_max_attempts: PositiveInt = 3
    timeout_answer_eval_seconds: PositiveFloat = 600
    timeout_retrieval_eval_seconds: PositiveFloat = 120
    timeout_eval_max_seconds: PositiveFloat = 3600
    timeout_retrieval_activity_seconds: PositiveFloat = 30
    timeout_retrieval_activity_total_seconds: PositiveFloat = 120
    timeout_budget_quote_seconds: PositiveFloat = 30
    timeout_budget_quote_total_seconds: PositiveFloat = 60
    timeout_record_result_seconds: PositiveFloat = 10
    timeout_record_result_total_seconds: PositiveFloat = 30
    timeout_local_dataset_load_seconds: PositiveFloat = 30
    timeout_hosted_dataset_load_seconds: PositiveFloat = 120
    timeout_dataset_export_http_seconds: PositiveFloat = 30
    timeout_dataset_fetch_http_seconds: PositiveFloat = 20

    @property
    def timeout_model_activity_seconds(self) -> float:
        return (
            self.timeout_model_request_max_seconds
            + self.timeout_activity_overhead_seconds
        )

    @property
    def timeout_model_activity_total_seconds(self) -> float:
        return (
            self.timeout_model_activity_seconds * self.model_max_attempts
            + self.timeout_activity_overhead_seconds
        )

    @property
    def timeout_eval_scoring_seconds(self) -> float:
        return (
            self.timeout_model_request_max_seconds
            + self.timeout_activity_overhead_seconds
        )

    @model_validator(mode="after")
    def validate_timeouts(self):
        if self.timeout_model_request_seconds > self.timeout_model_request_max_seconds:
            raise ValueError(
                "TIMEOUT_MODEL_REQUEST_SECONDS exceeds "
                "TIMEOUT_MODEL_REQUEST_MAX_SECONDS"
            )
        for stage in ("retrieval_activity", "budget_quote", "record_result"):
            if getattr(self, f"timeout_{stage}_total_seconds") < getattr(
                self, f"timeout_{stage}_seconds"
            ):
                raise ValueError(
                    f"TIMEOUT_{stage.upper()}_TOTAL_SECONDS must cover one attempt"
                )
        if (
            max(self.timeout_answer_eval_seconds, self.timeout_retrieval_eval_seconds)
            > self.timeout_eval_max_seconds
        ):
            raise ValueError("Default eval timeouts exceed TIMEOUT_EVAL_MAX_SECONDS")
        return self

    def timeout_snapshot(self) -> dict[str, float | int]:
        """Only non-secret timeout/retry settings belong in workflow history."""
        return {
            name: getattr(self, name)
            for name in type(self).model_fields
            if name.startswith("timeout_") or name == "model_max_attempts"
        }

    @classmethod
    def from_timeout_snapshot(cls, snapshot: dict[str, float | int] | None):
        """Reconstruct recorded policy; legacy workflows use declared defaults.

        Explicit values for every timeout field prevent environment changes
        from affecting workflow replay. Other Settings fields are not used
        by workflow code.
        """
        defaults = cls.model_construct().timeout_snapshot()
        return cls(**(defaults | (snapshot or {})))

    hold_reminder_window_minutes: PositiveInt = 120
    hold_notification_interval_seconds: PositiveInt = 600
    hold_notification_batch_size: PositiveInt = 200

    temporal_address: str = "localhost:7233"
    elasticsearch_url: str = "http://localhost:9200"
    kilt_index: str = "kilt"

    mcp_answer_model: str = "openai/gpt-5.6-terra"
    mcp_answer_max_tokens: PositiveInt = 1024
    mcp_answer_context_mode: Literal["compact", "full"] = "compact"
    mcp_answer_context_max_tokens: PositiveInt = 5000
    mcp_answer_context_max_paragraphs: PositiveInt = 12
    mcp_answer_passage_ranker: Literal["bm25"] = "bm25"
    mcp_verifier_model: str = ""
    eval_judge_model: str = ""
    # Deterministic judging; empty uses the provider default for models that
    # reject temperature overrides.
    eval_judge_temperature: NonNegativeFloat | None = 0
    ollama_api_base: str = "http://localhost:11434"
    openai_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None

    celery_broker_url: str = "redis://localhost:6379/0"

    otel_service_name: str = "api"
    otel_exporter_otlp_endpoint: str | None = None
    otel_metric_export_interval: PositiveInt = 60000

    langfuse_public_key: str | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_base_url: str = "https://cloud.langfuse.com"
    langfuse_tracing_environment: str = "local"
    langfuse_tracing_enabled: bool = True
    git_commit_sha: str | None = None

    @field_validator("eval_judge_temperature", mode="before")
    @classmethod
    def empty_temperature_uses_provider_default(cls, value):
        return None if value == "" else value

    @field_validator("eval_judge_model", "mcp_verifier_model", mode="before")
    @classmethod
    def resolve_answer_model_fallback(cls, value, info: ValidationInfo) -> str:
        return value or info.data["mcp_answer_model"]

    @property
    def otlp_enabled(self) -> bool:
        return self.otel_exporter_otlp_endpoint is not None
