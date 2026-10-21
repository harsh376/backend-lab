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
from backend.services.answer_synthesis.answer_synthesis import (
    AnswerSynthesisService,
    ExtractiveSynthesis,
)


def test_disabled_without_credentials(monkeypatch):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    telemetry.client.cache_clear()
    assert telemetry.client() is None
    with telemetry.observation("disabled") as span:
        assert span is None
    assert telemetry.current_context() is None
    telemetry.client.cache_clear()


@pytest.mark.parametrize("sha", ["a" * 40, ""])
def test_client_records_build_commit_as_release(monkeypatch, sha):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    monkeypatch.setenv("LANGFUSE_TRACING_ENABLED", "true")
    monkeypatch.setenv("GIT_COMMIT_SHA", sha)
    factory = Mock()
    monkeypatch.setattr(telemetry, "Langfuse", factory)
    monkeypatch.setattr(telemetry.atexit, "register", Mock())
    telemetry.client.cache_clear()
    try:
        assert telemetry.client() is factory.return_value
        assert factory.call_args.kwargs["release"] == (sha or None)
    finally:
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
        with provider.get_tracer("mcp-python-sdk").start_as_current_span(
            "answer", attributes={"gen_ai.operation.name": "execute_tool"}
        ):
            started = await server.answer("question")
        request = temporal.start_workflow.call_args.args[1]
        assert request.trace_context
        passage = Passage("v:1:0", "v", "1", 0, "Title", "Evidence")
        activities = AnswerActivities(
            Mock(aretrieve_passages=AsyncMock(return_value=[asdict(passage)])),
            AnswerSynthesisService(ExtractiveSynthesis()),
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
        root = next(s for s in spans if s.name == "answer")
        children = [s for s in spans if s.name != "answer"]
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
        assert root.attributes["langfuse.observation.type"] == "tool"
        assert any(s.status.status_code == StatusCode.ERROR for s in children)
        assert started["run_id"] == temporal.start_workflow.call_args.kwargs["id"]
        assert root.attributes["langfuse.observation.input"] == "question"
        assert root.attributes["langfuse.observation.output"] == started["run_id"]
        retrieval = next(s for s in children if s.name == "retrieve_answer_evidence")
        assert json.loads(retrieval.attributes["langfuse.observation.input"]) == {
            "request": asdict(request),
        }
        assert json.loads(retrieval.attributes["langfuse.observation.output"]) == [
            asdict(passage)
        ]
        synthesis = next(s for s in children if s.name == "synthesize_answer")
        assert json.loads(synthesis.attributes["langfuse.observation.input"]) == {
            "data": asdict(
                SynthesisInput(request.question, [passage], request.trace_context)
            ),
        }
        assert json.loads(
            synthesis.attributes["langfuse.observation.output"]
        ) == asdict(result)
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
        with provider.get_tracer("mcp-python-sdk").start_as_current_span(
            "get_answer", attributes={"gen_ai.operation.name": "execute_tool"}
        ):
            await server.get_answer(started["run_id"])
        instance.flush()
        poll = next(s for s in exporter.get_finished_spans() if s.name == "get_answer")
        assert poll.attributes["langfuse.observation.type"] == "tool"
        assert len(exporter.get_finished_spans()) == 5
        assert poll.attributes["langfuse.observation.output"] == "RUNNING"
        assert poll.attributes["langfuse.observation.input"] == started["run_id"]
        exporter.clear()
        server._get_answer.return_value = {
            "run_id": started["run_id"],
            "status": "COMPLETED",
            "result": asdict(result),
        }
        with provider.get_tracer("mcp-python-sdk").start_as_current_span(
            "get_answer", attributes={"gen_ai.operation.name": "execute_tool"}
        ):
            completed = await server.get_answer(started["run_id"])
        instance.flush()
        poll = exporter.get_finished_spans()[0]
        assert poll.attributes["langfuse.observation.output"] == (
            f"{result.short_answer}\n\n{result.explanation}"
        )
        assert completed["result"] == asdict(result)
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
        git_commit_sha="b" * 40,
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
            release="b" * 40,
            tracing_enabled=True,
        )
        register.assert_called_once_with(factory.return_value.shutdown)
        assert "sk-lf-config" not in repr(settings)
    finally:
        telemetry.client.cache_clear()


async def test_observe_disabled_preserves_signature_and_defaults(monkeypatch):
    from inspect import signature

    monkeypatch.setattr(telemetry, "client", lambda: None)

    async def original(question: str, limit: int = 5) -> dict:
        return {"question": question, "limit": limit}

    decorated = telemetry.observe("test")(original)
    assert signature(decorated) == signature(original)
    assert await decorated(question="question") == {"question": "question", "limit": 5}


@pytest.mark.parametrize("input_kind", ["dataclass", "dict", "argument"])
async def test_observe_infers_context_and_activity_metadata(monkeypatch, input_kind):
    from contextlib import contextmanager

    context = {"trace_id": "a" * 32, "parent_span_id": "b" * 16}
    captured = {}
    span = Mock()

    @contextmanager
    def observation(name, **kwargs):
        captured.update(kwargs)
        yield span

    monkeypatch.setattr(telemetry, "observation", observation)
    monkeypatch.setattr(telemetry.activity, "in_activity", lambda: True)
    monkeypatch.setattr(
        telemetry.activity,
        "info",
        lambda: Mock(
            workflow_id="answer-1",
            workflow_run_id="run-1",
            activity_id="activity-1",
            attempt=2,
        ),
    )

    @telemetry.observe("test")
    async def execute(data=None, trace_context=None):
        return "done"

    if input_kind == "dataclass":
        await execute(AnswerRequest("question", trace_context=context))
    elif input_kind == "dict":
        await execute({"trace_context": context})
    else:
        await execute(trace_context=context)
    assert captured["trace_context"] == context
    assert captured["metadata"] == {
        "answer_id": "answer-1",
        "temporal_run_id": "run-1",
        "activity_id": "activity-1",
        "attempt": 2,
    }
    span.update.assert_called_once_with(output="done")


async def test_observe_infers_function_and_registered_activity_names(monkeypatch):
    from contextlib import contextmanager

    from temporalio import activity

    names = []

    @contextmanager
    def observation(name, **kwargs):
        names.append(name)
        yield None

    monkeypatch.setattr(telemetry, "observation", observation)

    @telemetry.observe()
    async def plain_function():
        return "done"

    @activity.defn(name="registered-activity")
    @telemetry.observe()
    async def activity_function():
        return "done"

    @telemetry.observe("explicit")
    async def overridden():
        return "done"

    await plain_function()
    await activity_function()
    await overridden()
    assert names == ["plain_function", "registered-activity", "explicit"]


@pytest.mark.parametrize("thread_id", [None, "", 123, "é", "x" * 194])
async def test_chat_session_missing_or_invalid_metadata(thread_id):
    ctx = Mock(method="tools/call", meta={"threadId": thread_id})

    async def call_next(ctx):
        assert telemetry.current_session_id() is None
        return "done"

    assert await telemetry.chat_session(ctx, call_next) == "done"
    assert telemetry.current_session_id() is None


async def test_chat_sessions_propagate_without_leaking(monkeypatch):
    from temporalio.converter import DataConverter

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    instance = Langfuse(
        public_key="pk-lf-sessions",
        secret_key="sk-lf-test",
        tracer_provider=provider,
        span_exporter=exporter,
    )
    monkeypatch.setattr(telemetry, "client", lambda: instance)
    temporal = Mock(start_workflow=AsyncMock())
    monkeypatch.setattr(server, "temporal_client", AsyncMock(return_value=temporal))
    monkeypatch.setattr(
        server, "_get_answer", AsyncMock(return_value={"status": "RUNNING"})
    )

    async def submit(ctx):
        return await server.answer("question")

    async def poll(ctx):
        return await server.get_answer("kilt-answer-test")

    try:
        for chat_id in ["chat-a", "chat-b", "chat-a"]:
            ctx = Mock(method="tools/call", meta={"threadId": chat_id})
            with provider.get_tracer("mcp-python-sdk").start_as_current_span(
                "answer", attributes={"gen_ai.operation.name": "execute_tool"}
            ):
                await telemetry.chat_session(ctx, submit)
            request = temporal.start_workflow.call_args.args[1]
            assert request.session_id == f"codex:{chat_id}"
            converter = DataConverter.default
            request = (
                await converter.decode(
                    await converter.encode([request]), [AnswerRequest]
                )
            )[0]
            activities = AnswerActivities(
                Mock(aretrieve_passages=AsyncMock(return_value=[])),
                AnswerSynthesisService(ExtractiveSynthesis()),
            )
            await activities.aretrieve(request)
            await activities.agenerate(
                SynthesisInput(
                    request.question, [], request.trace_context, request.session_id
                )
            )
            with provider.get_tracer("mcp-python-sdk").start_as_current_span(
                "get_answer", attributes={"gen_ai.operation.name": "execute_tool"}
            ):
                await telemetry.chat_session(ctx, poll)
            assert telemetry.current_session_id() is None
        with provider.get_tracer("mcp-python-sdk").start_as_current_span(
            "no-chat", attributes={"gen_ai.operation.name": "execute_tool"}
        ):
            await telemetry.chat_session(Mock(method="tools/call", meta=None), poll)
        instance.flush()
        spans = exporter.get_finished_spans()
        for index, chat_id in enumerate(["chat-a", "chat-b", "chat-a"]):
            group = spans[index * 4 : (index + 1) * 4]
            assert len(group) == 4
            assert all(
                s.attributes.get("session.id") == f"codex:{chat_id}" for s in group
            )
        assert "session.id" not in spans[-1].attributes
    finally:
        instance.shutdown()


async def test_chat_session_resets_after_error():
    async def fail(ctx):
        assert telemetry.current_session_id() == "codex:chat-a"
        raise RuntimeError("failed")

    with pytest.raises(RuntimeError, match="failed"):
        await telemetry.chat_session(
            Mock(method="tools/call", meta={"threadId": "chat-a"}), fail
        )
    assert telemetry.current_session_id() is None


async def test_eval_tools_enrich_sdk_root_spans(monkeypatch):
    from temporalio.client import WorkflowExecutionStatus

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    instance = Langfuse(
        public_key="pk-lf-eval-tools",
        secret_key="sk-lf-test",
        tracer_provider=provider,
        span_exporter=exporter,
    )
    monkeypatch.setattr(telemetry, "client", lambda: instance)
    results = [{"case_id": "case", "evaluators": {"answers": {"correctness": 1}}}]
    handle = Mock(
        describe=AsyncMock(return_value=Mock(status=WorkflowExecutionStatus.COMPLETED)),
        result=AsyncMock(return_value=results),
    )
    temporal = Mock(start_workflow=AsyncMock())
    temporal.get_workflow_handle.return_value = handle
    monkeypatch.setattr(server.Client, "connect", AsyncMock(return_value=temporal))
    try:
        with provider.get_tracer("mcp-python-sdk").start_as_current_span(
            "run_evals", attributes={"gen_ai.operation.name": "execute_tool"}
        ):
            started = await server.run_evals(limit=1, timeout=120)
            parent = telemetry.current_context()
        assert temporal.start_workflow.call_args.args[1].trace_context == parent
        with provider.get_tracer("mcp-python-sdk").start_as_current_span(
            "get_evals", attributes={"gen_ai.operation.name": "execute_tool"}
        ):
            completed = await server.get_evals(started["run_id"])
        instance.flush()
        spans = exporter.get_finished_spans()
        assert len(spans) == 2
        submission, poll = spans
        assert json.loads(submission.attributes["langfuse.observation.input"]) == {
            "case_id": None,
            "limit": 1,
            "tags": None,
            "timeout": 120,
            "retrieval_k": 5,
        }
        assert (
            json.loads(submission.attributes["langfuse.observation.output"]) == started
        )
        assert json.loads(poll.attributes["langfuse.observation.output"]) == completed
        assert completed["results"] == results
        for span in spans:
            assert span.parent is None
            assert span.attributes["langfuse.observation.type"] == "tool"
            assert (
                span.attributes["langfuse.observation.metadata.eval_run_id"]
                == started["run_id"]
            )
    finally:
        instance.shutdown()
