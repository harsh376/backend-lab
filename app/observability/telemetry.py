"""OpenTelemetry SDK and OTLP exporter configuration."""

from dataclasses import dataclass

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from app.config import Settings


@dataclass(frozen=True, slots=True)
class Telemetry:
    tracer_provider: TracerProvider
    meter_provider: MeterProvider

    def shutdown(self) -> None:
        """Flush pending telemetry and stop exporter worker threads."""

        self.tracer_provider.shutdown()
        self.meter_provider.shutdown()


def configure_telemetry(settings: Settings) -> Telemetry:
    """Configure OTel providers, enabling OTLP when an endpoint is supplied."""

    resource = Resource.create({SERVICE_NAME: settings.otel_service_name})

    tracer_provider = TracerProvider(resource=resource)
    metric_readers: list[PeriodicExportingMetricReader] = []
    if settings.trace_otlp_enabled:
        tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    if settings.metric_otlp_enabled:
        metric_readers.append(PeriodicExportingMetricReader(OTLPMetricExporter()))

    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=metric_readers,
    )
    trace.set_tracer_provider(tracer_provider)
    metrics.set_meter_provider(meter_provider)
    return Telemetry(tracer_provider, meter_provider)
