"""Tests for application-level OpenTelemetry instruments."""

from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from backend.metrics import OpenTelemetryMetrics


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


def test_repository_failure_identifies_the_bounded_operation() -> None:
    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    application_metrics = OpenTelemetryMetrics(provider)

    application_metrics.record_repository_failure("create")

    data = reader.get_metrics_data()
    metrics = {
        metric.name: metric
        for resource_metrics in data.resource_metrics
        for scope_metrics in resource_metrics.scope_metrics
        for metric in scope_metrics.metrics
    }
    point = metrics["title.repository.failures"].data.data_points[0]
    assert point.value == 1
    assert point.attributes == {"title.operation": "create"}
    provider.shutdown()
