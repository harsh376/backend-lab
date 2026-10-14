"""Bounded-cardinality application metrics backed by OpenTelemetry."""

from typing import Protocol

from opentelemetry import metrics
from opentelemetry.metrics import Counter, MeterProvider


class Metrics(Protocol):
    def record_title_operation(self, operation: str, outcome: str) -> None: ...

    def record_repository_failure(self, operation: str) -> None: ...


class OpenTelemetryMetrics:
    def __init__(self, meter_provider: MeterProvider | None = None) -> None:
        meter = (meter_provider or metrics.get_meter_provider()).get_meter(
            "backend.metrics"
        )
        self._title_operations: Counter = meter.create_counter(
            "title.operations",
            unit="{operation}",
            description="Number of title operations",
        )
        self._repository_failures: Counter = meter.create_counter(
            "title.repository.failures",
            unit="{failure}",
            description="Number of title repository failures",
        )

    def record_title_operation(self, operation: str, outcome: str) -> None:
        self._title_operations.add(
            1,
            {
                "title.operation": operation,
                "title.outcome": outcome,
            },
        )

    def record_repository_failure(self, operation: str) -> None:
        self._repository_failures.add(1, {"title.operation": operation})
