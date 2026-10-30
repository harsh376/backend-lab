"""Verify adapters accept a model without constructing a provider client."""

import json
from unittest.mock import AsyncMock, Mock

import litellm
import pytest

from backend.llm import LiteLLMStructuredModel, StructuredCompletion
from backend.services.answer_synthesis.answer_synthesis import (
    AnswerResult,
    FullArticleSynthesisService,
    Paragraph,
    SynthesisInput,
)
from backend.services.answer_verification.answer_verification import (
    LiteLLMVerification,
    VerificationInput,
)


@pytest.mark.parametrize("verification", [False, True])
async def test_injected_model(verification):
    paragraph = Paragraph("v:1:0", "v", "1", 0, "Magazine", "It began in 1844.")
    content = (
        {"supported": True, "reason": "The paragraph gives 1844."}
        if verification
        else {
            "short_answer": "1844",
            "explanation": "It began in 1844.",
            "citation_ids": [paragraph.paragraph_ref],
            "abstained": False,
        }
    )
    response = litellm.ModelResponse(
        choices=[
            {
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": json.dumps(content)},
            }
        ]
    )
    model = Mock(
        provider="fake",
        model="fake/model",
        complete=AsyncMock(
            return_value=StructuredCompletion(
                response,
                {"total_tokens": 10},
                0.001,
            )
        ),
    )
    if verification:
        adapter = LiteLLMVerification(model=model)
        result = await adapter.verify(
            VerificationInput(
                "When?", AnswerResult("1844", "It began in 1844.", [paragraph])
            )
        )
        assert result.supported
    else:
        adapter = FullArticleSynthesisService(model=model)
        result = await adapter.synthesize(SynthesisInput("When?", [paragraph]))
        assert result.short_answer == "1844"
    assert adapter.model is model
    assert not isinstance(adapter, LiteLLMStructuredModel)
    assert result.provider == "fake"
    assert result.model == "fake/model"
    assert result.usage == {"total_tokens": 10}
    assert result.usage_cost_usd == 0.001
    model.complete.assert_awaited_once()
    assert model.complete.call_args.kwargs["schema_name"] == (
        "evidence_verification" if verification else "evidence_answer"
    )


async def test_ollama_translation_without_cloud_credentials(monkeypatch):
    import httpx
    from pydantic import BaseModel

    from backend.config import Settings

    class Answer(BaseModel):
        answer: str

    async def send(client, request, **kwargs):
        assert str(request.url) == "http://localhost:11434/api/chat"
        assert request.extensions["timeout"]["read"] == 180
        body = json.loads(request.content)
        assert body["model"] == "qwen3.8"
        assert body["format"] == Answer.model_json_schema()
        assert body["think"] is False
        assert body["stream"] is False
        assert "authorization" not in request.headers
        return httpx.Response(
            200,
            request=request,
            json={
                "model": "qwen3.8",
                "created_at": "2026-10-15T12:00:00Z",
                "message": {"role": "assistant", "content": '{"answer":"1844"}'},
                "done": True,
                "done_reason": "stop",
                "prompt_eval_count": 10,
                "eval_count": 5,
            },
        )

    monkeypatch.setattr(httpx.AsyncClient, "send", send)
    model = LiteLLMStructuredModel(
        Settings(
            _env_file=None,
            mcp_answer_model="ollama_chat/qwen3.8",
            timeout_model_request_seconds=180,
            openai_api_key=None,
            anthropic_api_key=None,
        )
    )
    result = await model.complete(
        [{"role": "user", "content": "When?"}],
        response_schema=Answer,
        schema_name="answer",
        prompt_version="test",
        observation_name="test",
    )
    assert json.loads(result.response.choices[0].message.content) == {"answer": "1844"}
    assert result.usage["total_tokens"] == 15


@pytest.mark.parametrize("temperature", [None, 0.0])
async def test_temperature_is_sent_only_when_configured(monkeypatch, temperature):
    from pydantic import BaseModel

    from backend.config import Settings

    class Answer(BaseModel):
        answer: str

    response = litellm.ModelResponse(
        choices=[
            {
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": '{"answer":"1844"}'},
            }
        ],
        usage={"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
    )
    acompletion = AsyncMock(return_value=response)
    monkeypatch.setattr(litellm, "acompletion", acompletion)
    model = LiteLLMStructuredModel(
        Settings(_env_file=None, mcp_answer_model="ollama_chat/qwen3.8"),
        temperature=temperature,
    )
    await model.complete(
        [{"role": "user", "content": "When?"}],
        response_schema=Answer,
        schema_name="answer",
        prompt_version="test",
        observation_name="test",
    )
    kwargs = acompletion.call_args.kwargs
    if temperature is None:
        assert "temperature" not in kwargs
    else:
        assert kwargs["temperature"] == temperature
