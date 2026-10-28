import json
from dataclasses import replace
from unittest.mock import AsyncMock, Mock

import litellm
import pytest
from temporalio.converter import DataConverter
from temporalio.exceptions import ApplicationError

from apps.mcp.agent.activities import AnswerActivities
from backend.config import Settings
from backend.services.answer_synthesis.answer_synthesis import (
    AnswerResult,
    Paragraph,
    VerificationResult,
)
from backend.services.answer_verification.answer_verification import (
    AnswerVerificationService,
    LiteLLMVerification,
    VerificationInput,
)


@pytest.fixture
def data():
    paragraph = Paragraph("v:1:0", "v", "1", 0, "Magazine", "It began in 1844.")
    return VerificationInput(
        "When did it begin?",
        AnswerResult(
            "1844",
            "It began in 1844.",
            [paragraph],
            usage={"total_tokens": 120},
            usage_cost_usd=0.001,
        ),
        {"trace_id": "a" * 32, "parent_span_id": "b" * 16},
        "codex:chat-a",
    )


@pytest.fixture
def completion(monkeypatch):
    response = litellm.ModelResponse(
        model="returned-model",
        choices=[
            {
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": json.dumps(
                        {"supported": True, "reason": "The cited paragraph gives 1844."}
                    ),
                },
            }
        ],
        usage={"prompt_tokens": 80, "completion_tokens": 20, "total_tokens": 100},
    )
    call = AsyncMock(return_value=response)
    monkeypatch.setattr(litellm, "acompletion", call)
    monkeypatch.setattr(litellm, "completion_cost", Mock(return_value=0.002))
    return call


def adapter(model=None, **kwargs):
    return LiteLLMVerification(
        Settings(
            mcp_answer_model="openai/synthesis-model",
            mcp_verifier_model=model,
            openai_api_key="test-openai",
            anthropic_api_key="test-anthropic",
        ),
        **kwargs,
    )


@pytest.mark.parametrize("model", [None, "anthropic/verifier-model"])
async def test_supported_answer_and_independent_accounting(data, completion, model):
    result = await AnswerVerificationService(adapter(model)).verify(data)
    assert not result.abstained
    assert result.citations == data.answer.citations
    assert result.usage == {"total_tokens": 120}
    assert result.usage_cost_usd == 0.001
    assert result.verification.supported
    assert result.verification.usage["total_tokens"] == 100
    assert result.verification.usage_cost_usd == 0.002
    request = completion.call_args.kwargs
    assert request["model"] == (model or "openai/synthesis-model")
    assert request["api_key"] == ("test-anthropic" if model else "test-openai")
    assert request["num_retries"] == 0
    assert request["response_format"]["json_schema"]["name"] == "evidence_verification"
    payload = json.loads(request["messages"][1]["content"])
    assert payload["cited_paragraphs"][0]["text"] == "It began in 1844."
    assert "usage" not in payload
    converter = DataConverter.default
    encoded = await converter.encode([result, data])
    assert await converter.decode(encoded, [AnswerResult, VerificationInput]) == [
        result,
        data,
    ]


@pytest.mark.parametrize(
    "content,finish",
    [
        ('{"supported":false,"reason":"The year is unsupported."}', "stop"),
        ("not json", "stop"),
        (None, "stop"),
        ("{}", "stop"),
        ('{"supported":"true","reason":"yes"}', "stop"),
        ('{"supported":true,"reason":""}', "stop"),
        ('{"supported":true,"reason":"supported"}', "length"),
        ('{"supported":true,"reason":"supported"}', "content_filter"),
    ],
)
async def test_unsupported_or_invalid_judgment_abstains(
    data, completion, content, finish
):
    completion.return_value.choices[0].message.content = content
    completion.return_value.choices[0].finish_reason = finish
    result = await AnswerVerificationService(adapter()).verify(data)
    assert result.abstained
    assert result.short_answer == ""
    assert result.citations == []
    assert not result.verification.supported
    assert result.verification.reason
    assert result.verification.usage["total_tokens"] == 100
    assert result.usage == data.answer.usage
    assert data.answer.short_answer == "1844"


@pytest.mark.parametrize("abstained", [True, False])
async def test_no_evidence_or_existing_abstention_skips_model(
    data, completion, abstained
):
    data.answer = replace(data.answer, abstained=abstained, citations=[])
    result = await AnswerVerificationService(adapter()).verify(data)
    assert result.abstained
    assert result.short_answer == ""
    completion.assert_not_awaited()


async def test_provider_failure_sanitized_and_transient_failure_propagates(
    data, completion
):
    activities = AnswerActivities(Mock(), Mock(), AnswerVerificationService(adapter()))
    completion.side_effect = litellm.AuthenticationError(
        message="sensitive", llm_provider="openai", model="model"
    )
    with pytest.raises(ApplicationError) as caught:
        await activities.averify(data)
    assert caught.value.non_retryable
    assert "sensitive" not in str(caught.value)
    completion.side_effect = litellm.Timeout(
        message="timeout", model="model", llm_provider="openai"
    )
    with pytest.raises(litellm.Timeout):
        await activities.averify(data)


async def test_verifier_can_be_replaced(data):
    judgment = VerificationResult(False, "Unsupported year.", "fake", "fake/model")
    fake = Mock(verify=AsyncMock(return_value=judgment))
    result = await AnswerVerificationService(fake).verify(data)
    assert result.abstained
    fake.verify.assert_awaited_once_with(data)


async def test_empty_choices_abstains(data, completion):
    completion.return_value.choices = []
    result = await AnswerVerificationService(adapter()).verify(data)
    assert result.abstained
    assert result.verification.usage["total_tokens"] == 100
