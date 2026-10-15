import json
from dataclasses import replace
from unittest.mock import AsyncMock, Mock

import httpx
import litellm
import pytest

from backend.config import Settings
from backend.llm import ModelProviderError
from backend.services.answer_synthesis.answer_synthesis import (
    AnswerResult,
    AnswerSynthesisService,
    ExtractiveSynthesis,
    LiteLLMSynthesis,
    Passage,
    SynthesisInput,
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
    return call


def settings(model="openai/gpt-5.6-terra"):
    return Settings(
        mcp_answer_model=model,
        openai_api_key="test-openai-key",
        anthropic_api_key="test-anthropic-key",
    )


@pytest.mark.parametrize(
    "model,key",
    [
        ("openai/gpt-5.6-terra", "test-openai-key"),
        ("anthropic/claude-sonnet-5", "test-anthropic-key"),
    ],
)
async def test_provider_selection_and_original_citations(
    completion, evidence, model, key
):
    synthesize = AnswerSynthesisService(LiteLLMSynthesis(settings(model)))
    result = await synthesize.synthesize(
        SynthesisInput("When did it begin?", [evidence])
    )
    assert result.short_answer == "1844"
    assert result.citations == [evidence]
    assert result.citations[0] is evidence
    assert result.provider == model.split("/")[0]
    assert result.model == model
    assert result.usage == {
        "prompt_tokens": 100,
        "completion_tokens": 20,
        "total_tokens": 120,
    }
    assert result.usage_cost_usd == 0.001
    args = completion.call_args.kwargs
    assert args["model"] == model
    assert args["api_key"] == key
    assert args["num_retries"] == 0
    assert args["caching"] is False
    assert args["timeout"] < 60  # Temporal's activity start-to-close timeout
    assert args["response_format"]["json_schema"]["strict"] is True
    assert json.loads(args["messages"][1]["content"])["passages"][0]["text"] == (
        evidence.text
    )


@pytest.mark.parametrize(
    "content,finish",
    [
        ("not json", "stop"),
        ('{"short_answer":"1844"}', "stop"),
        (None, "stop"),
        ("{}", "length"),
        ("{}", "content_filter"),
        (
            json.dumps(
                {
                    "short_answer": "1844",
                    "explanation": "x",
                    "citation_ids": ["invented"],
                    "abstained": False,
                }
            ),
            "stop",
        ),
        (
            json.dumps(
                {
                    "short_answer": "1844",
                    "explanation": "x",
                    "citation_ids": [],
                    "abstained": False,
                }
            ),
            "stop",
        ),
        (
            json.dumps(
                {
                    "short_answer": " ",
                    "explanation": "x",
                    "citation_ids": ["v:1:0"],
                    "abstained": False,
                }
            ),
            "stop",
        ),
        (
            json.dumps(
                {
                    "short_answer": "1844",
                    "explanation": "insufficient evidence",
                    "citation_ids": ["v:1:0"],
                    "abstained": True,
                }
            ),
            "stop",
        ),
    ],
)
async def test_unusable_answers_abstain_without_losing_usage(
    completion, evidence, content, finish
):
    completion.return_value.choices[0].message.content = content
    completion.return_value.choices[0].finish_reason = finish
    result = await AnswerSynthesisService(LiteLLMSynthesis(settings())).synthesize(
        SynthesisInput("question", [evidence])
    )
    assert result.abstained
    assert result.short_answer == ""
    assert result.citations == []
    assert result.usage["total_tokens"] == 120
    assert result.usage_cost_usd == 0.001


async def test_no_evidence_skips_provider(completion):
    result = await AnswerSynthesisService(LiteLLMSynthesis(settings())).synthesize(
        SynthesisInput("question", [])
    )
    assert result.abstained
    assert result.usage == {}
    assert result.usage_cost_usd is None
    completion.assert_not_awaited()


async def test_unknown_pricing_keeps_answer(completion, evidence, monkeypatch):
    monkeypatch.setattr(
        litellm, "completion_cost", Mock(side_effect=ValueError("unknown"))
    )
    result = await AnswerSynthesisService(LiteLLMSynthesis(settings())).synthesize(
        SynthesisInput("question", [evidence])
    )
    assert result.short_answer == "1844"
    assert result.usage_cost_usd is None


@pytest.mark.parametrize("model", ["gpt-5.6-terra", "openai/", "gemini/model"])
def test_invalid_provider_configuration(model):
    with pytest.raises(ValueError, match="MCP_ANSWER_MODEL"):
        AnswerSynthesisService(LiteLLMSynthesis(settings(model)))


@pytest.mark.parametrize(
    "provider,key_field",
    [
        ("openai", "openai_api_key"),
        ("anthropic", "anthropic_api_key"),
    ],
)
def test_missing_credentials(provider, key_field):
    config = settings(f"{provider}/model")
    setattr(config, key_field, None)
    with pytest.raises(ValueError, match="API_KEY"):
        LiteLLMSynthesis(config)
    assert "test-openai-key" not in repr(settings())
    assert "test-anthropic-key" not in repr(settings())
    assert "test-openai-key" not in repr(LiteLLMSynthesis(settings()))


async def test_authentication_error_is_not_retried(completion, evidence):
    completion.side_effect = litellm.AuthenticationError(
        message="sensitive provider message", llm_provider="openai", model="model"
    )
    with pytest.raises(ModelProviderError) as caught:
        await AnswerSynthesisService(LiteLLMSynthesis(settings())).synthesize(
            SynthesisInput("question", [evidence])
        )
    assert caught.value.error_type == "AuthenticationError"
    assert "sensitive" not in str(caught.value)
    completion.assert_awaited_once()


async def test_transient_error_reaches_caller(completion, evidence):
    error = litellm.Timeout(message="timeout", model="model", llm_provider="openai")
    completion.side_effect = error
    with pytest.raises(litellm.Timeout):
        await AnswerSynthesisService(LiteLLMSynthesis(settings())).synthesize(
            SynthesisInput("question", [evidence])
        )
    completion.assert_awaited_once()


@pytest.mark.parametrize(
    "model,host",
    [
        ("openai/gpt-5.6-terra", "api.openai.com"),
        ("anthropic/claude-sonnet-5", "api.anthropic.com"),
    ],
)
@pytest.mark.parametrize("status", [200, 429])
async def test_real_litellm_provider_translation(
    monkeypatch, evidence, model, host, status
):
    """Exercise LiteLLM itself with HTTP stubbed at the transport boundary."""
    content = json.dumps(
        {
            "short_answer": "1844",
            "explanation": "It began in 1844.",
            "citation_ids": [evidence.passage_id],
            "abstained": False,
        }
    )
    requests = []

    async def send(client, request, **kwargs):
        requests.append(request)
        assert request.url.host == host
        if status == 429:
            return httpx.Response(
                429,
                json={"error": {"type": "rate_limit_error", "message": "Rate limited"}},
                request=request,
            )
        body = json.loads(request.content)
        assert body["model"] == model.split("/", 1)[1]
        if model.startswith("openai/"):
            assert body["response_format"]["json_schema"]["strict"] is True
            payload = {
                "id": "chatcmpl-stub",
                "object": "chat.completion",
                "created": 1,
                "model": body["model"],
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": content},
                    }
                ],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 20,
                    "total_tokens": 120,
                },
            }
        else:
            assert body.get("output_format") or body.get("output_config")
            payload = {
                "id": "msg-stub",
                "type": "message",
                "role": "assistant",
                "model": body["model"],
                "content": [{"type": "text", "text": content}],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 100, "output_tokens": 20},
            }
        return httpx.Response(200, json=payload, request=request)

    monkeypatch.setattr(httpx.AsyncClient, "send", send)
    synthesize = AnswerSynthesisService(LiteLLMSynthesis(settings(model)))
    data = SynthesisInput("When did it begin?", [evidence])
    if status == 429:
        with pytest.raises(litellm.RateLimitError):
            await synthesize.synthesize(data)
    else:
        result = await synthesize.synthesize(data)
        assert result.short_answer == "1844"
        assert result.citations == [evidence]
        assert result.usage["prompt_tokens"] == 100
        assert result.usage["completion_tokens"] == 20
    assert len(requests) == 1


async def test_extractive_adapter():
    service = AnswerSynthesisService(ExtractiveSynthesis())
    empty = await service.synthesize(SynthesisInput("question", []))
    assert empty.abstained
    passage = Passage("v:1:0", "v", "1", 0, "Title", "Original text")
    result = await service.synthesize(SynthesisInput("question", [passage]))
    assert result.short_answer == passage.text
    assert result.citations == [passage]
    assert result.usage == {}
    assert result.usage_cost_usd is None


async def test_custom_adapter_needs_only_synthesize_method():
    passage = Passage("v:1:0", "v", "1", 0, "Title", "Original text")

    class CustomSynthesis:
        async def synthesize(self, data: SynthesisInput) -> AnswerResult:
            assert data.question == "question"
            return AnswerResult(
                "answer", "explanation", data.passages, provider="custom"
            )

    result = await AnswerSynthesisService(CustomSynthesis()).synthesize(
        SynthesisInput("question", [passage])
    )
    assert result.provider == "custom"
    assert result.short_answer == "answer"
    assert result.citations[0] is passage


@pytest.mark.parametrize("variation", ["forged", "missing", "empty", "abstained"])
async def test_shared_validation_preserves_accounting(variation):
    passage = Passage("v:1:0", "v", "1", 0, "Title", "Original text")
    result = AnswerResult(
        "answer",
        "explanation",
        [passage],
        provider="custom",
        model="custom/model",
        usage={"total_tokens": 120},
        usage_cost_usd=0.001,
    )
    if variation == "forged":
        result.citations = [replace(passage, text="Fabricated text")]
    elif variation == "missing":
        result.citations = []
    elif variation == "empty":
        result.short_answer = " "
    else:
        result.abstained = True
    adapter = Mock(synthesize=AsyncMock(return_value=result))
    data = SynthesisInput("question", [passage])
    checked = await AnswerSynthesisService(adapter).synthesize(data)
    adapter.synthesize.assert_awaited_once_with(data)
    assert checked.abstained
    assert checked.short_answer == ""
    assert checked.citations == []
    assert checked.provider == "custom"
    assert checked.model == "custom/model"
    assert checked.usage == {"total_tokens": 120}
    assert checked.usage_cost_usd == 0.001
    assert checked is not result
