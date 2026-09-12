"""Test-process configuration that mirrors the Compose telemetry mode."""

import os


def pytest_configure() -> None:
    os.environ["OTEL_SEMCONV_STABILITY_OPT_IN"] = "http"
