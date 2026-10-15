"""Optional Langfuse instrumentation outside deterministic workflow execution."""

import atexit
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, is_dataclass
from functools import lru_cache, wraps
from inspect import signature

from langfuse import Langfuse, propagate_attributes
from opentelemetry import trace
from temporalio import activity

from backend.config import Settings

_session_id: ContextVar[str | None] = ContextVar("langfuse_session_id", default=None)


def current_session_id() -> str | None:
    return _session_id.get()


async def chat_session(ctx, call_next):
    """Group tool calls by client-supplied Codex thread metadata, never transport ID."""
    if ctx.method != "tools/call":
        return await call_next(ctx)
    thread_id = (ctx.meta or {}).get("threadId")
    session_id = None
    if (
        isinstance(thread_id, str)
        and thread_id.strip()
        and thread_id.isascii()
        and len(thread_id) <= 193
    ):
        session_id = f"codex:{thread_id}"
    token = _session_id.set(session_id)
    try:
        with propagate_attributes(session_id=session_id):
            return await call_next(ctx)
    finally:
        _session_id.reset(token)


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
def observation(
    name,
    *,
    input=None,
    trace_context=None,
    metadata=None,
    as_type="span",
    session_id=None,
):
    instance = client()
    if instance is None:
        yield None
        return
    with (
        instance.start_as_current_observation(
            name=name,
            input=input,
            as_type=as_type,
            trace_context=trace_context,
            metadata=metadata,
        ) as span,
        propagate_attributes(session_id=session_id),
    ):
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


def observe(
    name=None, *, trace_context=None, metadata=None, as_type="span", reuse_current=False
):
    """Capture async arguments/results and infer trace context and Temporal metadata.

    Context comes from a trace_context argument or a top-level input's
    trace_context field. Outside activities, Temporal metadata is empty.
    Explicit callbacks override inferred context and extend activity metadata.
    Names default to the activity type (or its registered definition when called
    directly), then the function name. Explicit names override this inference.
    With reuse_current, enrich the SDK-owned tool span and retain its tool name.
    """

    def decorate(function):
        call_signature = signature(function)

        @wraps(function)
        async def wrapped(*args, **kwargs):
            bound = call_signature.bind(*args, **kwargs)
            bound.apply_defaults()
            arguments = {
                key: value
                for key, value in bound.arguments.items()
                if key not in {"self", "cls"}
            }
            span_metadata = _activity_metadata()
            if metadata:
                span_metadata.update(metadata(arguments))
            if reuse_current:
                instance = client()
                recording = trace.get_current_span().is_recording()
                if instance is not None and recording:
                    trace.get_current_span().set_attribute(
                        "langfuse.observation.type", as_type
                    )
                    instance.update_current_span(
                        input=_serialize(arguments), metadata=span_metadata
                    )
                result = await function(*args, **kwargs)
                if instance is not None and recording:
                    instance.update_current_span(output=_serialize(result))
                return result
            definition = getattr(wrapped, "__temporal_activity_definition", None)
            inferred_name = (
                activity.info().activity_type
                if activity.in_activity()
                else getattr(definition, "name", None) or function.__name__
            )
            with observation(
                name or inferred_name,
                input=_serialize(arguments),
                trace_context=(
                    trace_context(arguments)
                    if trace_context
                    else _trace_context(arguments)
                ),
                metadata=span_metadata,
                as_type=as_type,
                session_id=_session_from_arguments(arguments),
            ) as span:
                result = await function(*args, **kwargs)
                if span is not None:
                    span.update(output=_serialize(result))
                return result

        return wrapped

    return decorate


def update_metadata(metadata):
    """Attach metadata discovered during a decorated call to its current span."""
    instance = client()
    if instance is not None:
        instance.update_current_span(metadata=metadata)


def _serialize(value):
    """Convert nested dataclasses and containers to structured span payloads."""
    if is_dataclass(value) and not isinstance(value, type):
        return _serialize(asdict(value))
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize(item) for item in value]
    return value


def _trace_context(arguments):
    context = arguments.get("trace_context")
    if context:
        return context
    for value in arguments.values():
        context = (
            value.get("trace_context")
            if isinstance(value, dict)
            else getattr(value, "trace_context", None)
        )
        if context:
            return context
    return None


def _activity_metadata() -> dict:
    if not activity.in_activity():
        return {}
    info = activity.info()
    return {
        "answer_id": info.workflow_id,
        "temporal_run_id": info.workflow_run_id,
        "activity_id": info.activity_id,
        "attempt": info.attempt,
    }


def _session_from_arguments(arguments):
    for value in arguments.values():
        session_id = (
            value.get("session_id")
            if isinstance(value, dict)
            else getattr(value, "session_id", None)
        )
        if session_id:
            return session_id
    return current_session_id()
