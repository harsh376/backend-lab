import json
from unittest.mock import AsyncMock, Mock

import litellm
import pytest
from langfuse import Langfuse
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from temporalio.exceptions import ApplicationError

from apps.mcp import telemetry
from apps.mcp.agent.activities import AnswerActivities
from apps.mcp.agent.models import Passage, SynthesisInput
from backend.config import Settings
from backend.services.answer_synthesis.answer_synthesis import (
    AnswerSynthesisService,
    LiteLLMSynthesis,
)


@pytest.fixture
def evidence():
    return Passage("v:1:0", "v", "1", 0, "Magazine", "It began in 1844.")


@pytest.fixture
def completion(monkeypatch, evidence):
    response = litellm.ModelResponse(
        model="returned-model",
        choices=[
            {
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": json.dumps(
                        {
                            "short_answer": "1844",
                            "explanation": "The magazine began in 1844.",
                            "citation_ids": [evidence.passage_id],
                            "abstained": False,
                        }
                    ),
                },
            }
        ],
        usage={"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
    )
    call = AsyncMock(return_value=response)
    monkeypatch.setattr(litellm, "acompletion", call)
    monkeypatch.setattr(litellm, "completion_cost", Mock(return_value=0.001))
    monkeypatch.setattr(telemetry, "client", lambda: None)
    return call


def settings(model="openai/gpt-5.6-terra"):
    return Settings(
        mcp_answer_model=model,
        openai_api_key="test-openai-key",
        anthropic_api_key="test-anthropic-key",
    )


async def test_generation_joins_activity_trace(completion, evidence, monkeypatch):
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    instance = Langfuse(
        public_key="pk-lf-synthesis",
        secret_key="sk-lf-test",
        tracer_provider=provider,
        span_exporter=exporter,
    )
    monkeypatch.setattr(telemetry, "client", lambda: instance)
    context = {"trace_id": "a" * 32, "parent_span_id": "b" * 16}
    try:
        await AnswerActivities(
            Mock(),
            AnswerSynthesisService(
                LiteLLMSynthesis(settings(), observation_factory=telemetry.observation)
            ),
        ).agenerate(SynthesisInput("question", [evidence], context, "codex:chat-a"))
        instance.flush()
        spans = exporter.get_finished_spans()
        generation = next(s for s in spans if s.name == "answer_model")
        activity = next(s for s in spans if s.name == "synthesize_answer")
        assert generation.parent.span_id == activity.context.span_id
        assert generation.context.trace_id == int(context["trace_id"], 16)
        assert generation.attributes["session.id"] == "codex:chat-a"
        assert generation.attributes["langfuse.observation.type"] == "generation"
        assert json.loads(
            generation.attributes["langfuse.observation.usage_details"]
        ) == {
            "input": 100,
            "output": 20,
        }
        assert "test-openai-key" not in str(generation.attributes)
    finally:
        instance.shutdown()


async def test_provider_rejection_becomes_non_retryable_temporal_error(
    completion, evidence
):
    completion.side_effect = litellm.AuthenticationError(
        message="sensitive provider message", llm_provider="openai", model="model"
    )
    activities = AnswerActivities(
        Mock(), AnswerSynthesisService(LiteLLMSynthesis(settings()))
    )
    with pytest.raises(ApplicationError) as caught:
        await activities.agenerate(SynthesisInput("question", [evidence]))
    assert caught.value.non_retryable
    assert caught.value.type == "AuthenticationError"
    assert "sensitive" not in str(caught.value)
