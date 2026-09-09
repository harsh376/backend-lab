"""Tests for application-level OpenTelemetry instruments."""

from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from app.observability.metrics import OpenTelemetryMetrics


def test_title_operation_has_only_bounded_attributes() -> None:
    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    application_metrics = OpenTelemetryMetrics(provider)

    application_metrics.record_title_operation("get", "success")

    data = reader.get_metrics_data()
    metric = data.resource_metrics[0].scope_metrics[0].metrics[0]
    point = metric.data.data_points[0]
    assert metric.name == "title.operations"
    assert point.value == 1
    assert point.attributes == {
        "title.operation": "get",
        "title.outcome": "success",
    }
    provider.shutdown()
