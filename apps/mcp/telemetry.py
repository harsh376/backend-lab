"""Optional Langfuse instrumentation outside deterministic workflow execution."""

import atexit
from contextlib import contextmanager
from functools import lru_cache

from langfuse import Langfuse
from opentelemetry import trace

from backend.config import Settings


@lru_cache(maxsize=1)
def client() -> Langfuse | None:
    settings = Settings()
    if (
        not settings.langfuse_tracing_enabled
        or not settings.langfuse_public_key
        or not settings.langfuse_secret_key
        or not settings.langfuse_secret_key.get_secret_value()
    ):
        return None
    instance = Langfuse(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key.get_secret_value(),
        base_url=settings.langfuse_base_url,
        environment=settings.langfuse_tracing_environment,
        tracing_enabled=settings.langfuse_tracing_enabled,
    )
    atexit.register(instance.shutdown)
    return instance


@contextmanager
def observation(name, *, input=None, trace_context=None, metadata=None, as_type="span"):
    instance = client()
    if instance is None:
        yield None
        return
    with instance.start_as_current_observation(
        name=name,
        input=input,
        as_type=as_type,
        trace_context=trace_context,
        metadata=metadata,
    ) as span:
        if trace_context and trace_context.get("parent_span_id"):
            # Langfuse 4 marks explicit remote contexts as application roots.
            # These are continuations of our already-exported submission span.
            current_span = trace.get_current_span()
            current_span.set_attribute("langfuse.internal.as_root", False)
            current_span.set_attribute("langfuse.internal.is_app_root", False)
        yield span


def current_context() -> dict[str, str] | None:
    instance = client()
    if instance is None:
        return None
    trace_id = instance.get_current_trace_id()
    parent_span_id = instance.get_current_observation_id()
    if trace_id and parent_span_id:
        return {"trace_id": trace_id, "parent_span_id": parent_span_id}
    return None
