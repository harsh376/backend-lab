import json
from dataclasses import asdict
from unittest.mock import AsyncMock, Mock

import pytest
from langfuse import Langfuse
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from apps.mcp import server, telemetry
from apps.mcp.agent.activities import AnswerActivities
from apps.mcp.agent.models import AnswerRequest, Passage, SynthesisInput


def test_disabled_without_credentials(monkeypatch):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    telemetry.client.cache_clear()
    assert telemetry.client() is None
    with telemetry.observation("disabled") as span:
        assert span is None
    assert telemetry.current_context() is None
    telemetry.client.cache_clear()


async def test_cross_process_context_and_errors(monkeypatch):
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    instance = Langfuse(
        public_key="pk-lf-test",
        secret_key="sk-lf-test",
        tracer_provider=provider,
        span_exporter=exporter,
    )
    monkeypatch.setattr(telemetry, "client", lambda: instance)
    temporal = Mock()
    temporal.start_workflow = AsyncMock()
    monkeypatch.setattr(server, "temporal_client", AsyncMock(return_value=temporal))
    try:
        started = await server.answer("question")
        request = temporal.start_workflow.call_args.args[1]
        assert request.trace_context
        passage = Passage("v:1:0", "v", "1", 0, "Title", "Evidence")
        activities = AnswerActivities(
            Mock(aretrieve_passages=AsyncMock(return_value=[asdict(passage)]))
        )
        assert await activities.aretrieve(request) == [passage]
        result = await activities.agenerate(
            SynthesisInput(request.question, [passage], request.trace_context)
        )
        assert not result.abstained
        activities.kilt.aretrieve_passages.side_effect = RuntimeError("unavailable")
        with pytest.raises(RuntimeError, match="unavailable"):
            await activities.aretrieve(request)
        instance.flush()
        spans = exporter.get_finished_spans()
        root = next(s for s in spans if s.name == "mcp.answer")
        children = [s for s in spans if s.name != "mcp.answer"]
        assert len(children) == 3
        assert all(s.context.trace_id == root.context.trace_id for s in children)
        assert all(s.parent.span_id == root.context.span_id for s in children)
        assert all(
            s.attributes.get("langfuse.internal.as_root") is False for s in children
        )
        assert all(
            s.attributes.get("langfuse.internal.is_app_root") is False for s in children
        )
        assert root.attributes.get("langfuse.internal.as_root") is not False
        assert any(s.status.status_code == StatusCode.ERROR for s in children)
        assert started["run_id"] == temporal.start_workflow.call_args.kwargs["id"]
        assert json.loads(root.attributes["langfuse.observation.input"]) == {
            "question": "question",
            "limit": 5,
        }
        retrieval = next(s for s in children if s.name == "retrieve_answer_evidence")
        assert json.loads(retrieval.attributes["langfuse.observation.input"]) == {
            "question": "question",
            "limit": 5,
        }
        synthesis = next(s for s in children if s.name == "synthesize_answer")
        assert json.loads(synthesis.attributes["langfuse.observation.input"]) == {
            "question": "question",
            "passages": [asdict(passage)],
        }
        monkeypatch.setattr(
            server,
            "_get_answer",
            AsyncMock(
                return_value={
                    "run_id": started["run_id"],
                    "status": "RUNNING",
                }
            ),
        )
        await server.get_answer(started["run_id"])
        instance.flush()
        poll = next(
            s for s in exporter.get_finished_spans() if s.name == "mcp.get_answer"
        )
        assert json.loads(poll.attributes["langfuse.observation.input"]) == {
            "run_id": started["run_id"],
        }
    finally:
        instance.shutdown()


async def test_trace_context_survives_temporal_serialization():
    from temporalio.converter import DataConverter

    context = {"trace_id": "a" * 32, "parent_span_id": "b" * 16}
    request = AnswerRequest("question", trace_context=context)
    converter = DataConverter.default
    payloads = await converter.encode([request])
    assert await converter.decode(payloads, [AnswerRequest]) == [request]


@pytest.mark.parametrize("enabled", ["false", "0", "no"])
def test_settings_disable_tracing(monkeypatch, enabled):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    monkeypatch.setenv("LANGFUSE_TRACING_ENABLED", enabled)
    telemetry.client.cache_clear()
    try:
        assert telemetry.client() is None
    finally:
        telemetry.client.cache_clear()


def test_client_uses_settings_explicitly(monkeypatch):
    from backend.config import Settings

    settings = Settings(
        langfuse_public_key="pk-lf-config",
        langfuse_secret_key="sk-lf-config",
        langfuse_base_url="https://us.cloud.langfuse.com",
        langfuse_tracing_environment="test",
        langfuse_tracing_enabled=True,
    )
    monkeypatch.setattr(telemetry, "Settings", lambda: settings)
    factory = Mock()
    monkeypatch.setattr(telemetry, "Langfuse", factory)
    register = Mock()
    monkeypatch.setattr(telemetry.atexit, "register", register)
    telemetry.client.cache_clear()
    try:
        assert telemetry.client() is factory.return_value
        assert telemetry.client() is factory.return_value
        factory.assert_called_once_with(
            public_key="pk-lf-config",
            secret_key="sk-lf-config",
            base_url="https://us.cloud.langfuse.com",
            environment="test",
            tracing_enabled=True,
        )
        register.assert_called_once_with(factory.return_value.shutdown)
        assert "sk-lf-config" not in repr(settings)
    finally:
        telemetry.client.cache_clear()
