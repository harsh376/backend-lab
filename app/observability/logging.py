"""Structured JSON logging configuration."""

import json
import logging
import sys
from datetime import UTC, datetime

from opentelemetry import trace
from opentelemetry.instrumentation.logging.handler import LoggingHandler
from opentelemetry.sdk._logs import LoggerProvider


class JsonStreamHandler(logging.StreamHandler):
    """Marker type used to avoid installing duplicate JSON handlers."""


class JsonFormatter(logging.Formatter):
    _standard_fields = frozenset(
        {
            "args",
            "asctime",
            "created",
            "exc_info",
            "exc_text",
            "filename",
            "funcName",
            "levelname",
            "levelno",
            "lineno",
            "module",
            "msecs",
            "message",
            "msg",
            "name",
            "pathname",
            "process",
            "processName",
            "relativeCreated",
            "stack_info",
            "thread",
            "threadName",
            "taskName",
        }
    )

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "event": record.getMessage(),
        }
        payload.update(
            {
                key: value
                for key, value in record.__dict__.items()
                if key not in self._standard_fields and not key.startswith("_")
            }
        )
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        span_context = trace.get_current_span().get_span_context()
        if span_context.is_valid:
            payload["trace_id"] = format(span_context.trace_id, "032x")
            payload["span_id"] = format(span_context.span_id, "016x")
        return json.dumps(payload, default=str)


def configure_logger(
    name: str = "api",
    logger_provider: LoggerProvider | None = None,
) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not any(isinstance(handler, JsonStreamHandler) for handler in logger.handlers):
        handler = JsonStreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
    if logger_provider is not None and not any(
        isinstance(handler, LoggingHandler) for handler in logger.handlers
    ):
        logger.addHandler(
            LoggingHandler(level=logging.NOTSET, logger_provider=logger_provider)
        )
    return logger
