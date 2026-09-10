"""OpenTelemetry SDK and OTLP exporter configuration."""

from dataclasses import dataclass

from opentelemetry import metrics, trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
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
    logger_provider: LoggerProvider | None

    def shutdown(self) -> None:
        """Flush pending telemetry and stop exporter worker threads."""

        try:
            self.tracer_provider.shutdown()
        finally:
            try:
                self.meter_provider.shutdown()
            finally:
                if self.logger_provider is not None:
                    self.logger_provider.shutdown()


def configure_telemetry(settings: Settings) -> Telemetry:
    """Configure OTel providers, enabling OTLP when an endpoint is supplied."""

    resource = Resource.create({SERVICE_NAME: settings.otel_service_name})
    endpoint = settings.otel_exporter_otlp_endpoint

    tracer_provider = TracerProvider(resource=resource)
    metric_readers: list[PeriodicExportingMetricReader] = []
    if settings.otlp_enabled:
        tracer_provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint))
        )
        metric_readers.append(
            PeriodicExportingMetricReader(
                OTLPMetricExporter(endpoint=endpoint),
                export_interval_millis=settings.otel_metric_export_interval,
            )
        )

    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=metric_readers,
    )
    trace.set_tracer_provider(tracer_provider)
    metrics.set_meter_provider(meter_provider)

    logger_provider: LoggerProvider | None = None
    if settings.otlp_enabled:
        logger_provider = LoggerProvider(resource=resource)
        logger_provider.add_log_record_processor(
            BatchLogRecordProcessor(OTLPLogExporter(endpoint=endpoint))
        )
        set_logger_provider(logger_provider)

    return Telemetry(tracer_provider, meter_provider, logger_provider)
