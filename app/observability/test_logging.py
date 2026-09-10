"""Tests for structured log and trace correlation."""

import json
import logging

from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import (
    InMemoryLogRecordExporter,
    SimpleLogRecordProcessor,
)
from opentelemetry.sdk.trace import TracerProvider

from app.observability.logging import JsonFormatter, configure_logger


def test_json_log_contains_active_trace_context() -> None:
    provider = TracerProvider()
    tracer = provider.get_tracer(__name__)
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="title_operation_completed",
        args=(),
        exc_info=None,
    )

    with tracer.start_as_current_span("test") as span:
        payload = json.loads(formatter.format(record))
        context = span.get_span_context()

    assert payload["trace_id"] == format(context.trace_id, "032x")
    assert payload["span_id"] == format(context.span_id, "016x")
    provider.shutdown()


def test_otel_log_handler_exports_trace_context_and_attributes() -> None:
    log_exporter = InMemoryLogRecordExporter()
    logger_provider = LoggerProvider()
    logger_provider.add_log_record_processor(SimpleLogRecordProcessor(log_exporter))
    tracer_provider = TracerProvider()
    tracer = tracer_provider.get_tracer(__name__)
    logger = configure_logger("test-otel-log-export", logger_provider)

    with tracer.start_as_current_span("test") as span:
        context = span.get_span_context()
        logger.info("title_operation_completed", extra={"request_id": "request-1"})

    record = log_exporter.get_finished_logs()[0].log_record
    assert record.trace_id == context.trace_id
    assert record.span_id == context.span_id
    assert record.attributes["request_id"] == "request-1"
    logger.handlers.clear()
    logger_provider.shutdown()
    tracer_provider.shutdown()
