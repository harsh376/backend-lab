"""OpenTelemetry SDK and OTLP exporter configuration."""

import os
from dataclasses import dataclass

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


@dataclass(frozen=True, slots=True)
class Telemetry:
    tracer_provider: TracerProvider
    meter_provider: MeterProvider

    def shutdown(self) -> None:
        """Flush pending telemetry and stop exporter worker threads."""

        self.tracer_provider.shutdown()
        self.meter_provider.shutdown()


def configure_telemetry() -> Telemetry:
    """Configure OTel providers, enabling OTLP when an endpoint is supplied."""

    resource = Resource.create(
        {SERVICE_NAME: os.getenv("OTEL_SERVICE_NAME", "title-api")}
    )

    tracer_provider = TracerProvider(resource=resource)
    metric_readers: list[PeriodicExportingMetricReader] = []
    if _trace_otlp_enabled():
        tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    if _metric_otlp_enabled():
        metric_readers.append(PeriodicExportingMetricReader(OTLPMetricExporter()))

    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=metric_readers,
    )
    trace.set_tracer_provider(tracer_provider)
    metrics.set_meter_provider(meter_provider)
    return Telemetry(tracer_provider, meter_provider)


def _trace_otlp_enabled() -> bool:
    return bool(
        os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
        or os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
    )


def _metric_otlp_enabled() -> bool:
    return bool(
        os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
        or os.getenv("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT")
    )
