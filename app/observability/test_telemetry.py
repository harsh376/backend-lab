"""Tests for OpenTelemetry provider and exporter configuration."""

from collections.abc import Sequence

from opentelemetry.sdk._logs import ReadableLogRecord
from opentelemetry.sdk._logs.export import LogRecordExporter, LogRecordExportResult
from opentelemetry.sdk.metrics.export import (
    MetricExporter,
    MetricExportResult,
    MetricsData,
)
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

from app.config import Settings
from app.observability import telemetry as telemetry_module


class StubSpanExporter(SpanExporter):
    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        pass

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        return True


class StubMetricExporter(MetricExporter):
    def export(
        self,
        metrics_data: MetricsData,
        timeout_millis: float = 10_000,
        **kwargs,
    ) -> MetricExportResult:
        return MetricExportResult.SUCCESS

    def shutdown(self, timeout_millis: float = 30_000, **kwargs) -> None:
        pass

    def force_flush(self, timeout_millis: float = 10_000) -> bool:
        return True


class StubLogExporter(LogRecordExporter):
    def export(self, batch: Sequence[ReadableLogRecord]) -> LogRecordExportResult:
        return LogRecordExportResult.SUCCESS

    def shutdown(self) -> None:
        pass

    def force_flush(self, timeout_millis: int = 10_000) -> bool:
        return True


def test_configured_endpoints_are_passed_to_each_exporter(monkeypatch) -> None:
    endpoints: dict[str, str | None] = {}

    def span_exporter(*, endpoint: str | None) -> StubSpanExporter:
        endpoints["traces"] = endpoint
        return StubSpanExporter()

    def metric_exporter(*, endpoint: str | None) -> StubMetricExporter:
        endpoints["metrics"] = endpoint
        return StubMetricExporter()

    def log_exporter(*, endpoint: str | None) -> StubLogExporter:
        endpoints["logs"] = endpoint
        return StubLogExporter()

    monkeypatch.setattr(telemetry_module, "OTLPSpanExporter", span_exporter)
    monkeypatch.setattr(telemetry_module, "OTLPMetricExporter", metric_exporter)
    monkeypatch.setattr(telemetry_module, "OTLPLogExporter", log_exporter)
    settings = Settings(
        _env_file=None,
        otel_exporter_otlp_endpoint="http://common:4317",
        otel_metric_export_interval=12345,
    )

    telemetry = telemetry_module.configure_telemetry(settings)

    assert endpoints == {
        "traces": "http://common:4317",
        "metrics": "http://common:4317",
        "logs": "http://common:4317",
    }
    metric_reader = telemetry.meter_provider._metric_readers[0]
    assert metric_reader._export_interval_millis == 12345
    telemetry.shutdown()
