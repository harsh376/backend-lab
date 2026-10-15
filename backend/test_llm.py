"""Verify adapters accept a model without constructing a provider client."""

import json
from unittest.mock import AsyncMock, Mock

import litellm
import pytest

from backend.llm import LiteLLMStructuredModel, StructuredCompletion
from backend.services.answer_synthesis.answer_synthesis import (
    AnswerResult,
    LiteLLMSynthesis,
    Passage,
    SynthesisInput,
)
from backend.services.answer_verification.answer_verification import (
    LiteLLMVerification,
    VerificationInput,
)


@pytest.mark.parametrize("verification", [False, True])
async def test_injected_model(verification):
    passage = Passage("v:1:0", "v", "1", 0, "Magazine", "It began in 1844.")
    content = (
        {"supported": True, "reason": "The passage gives 1844."}
        if verification
        else {
            "short_answer": "1844",
            "explanation": "It began in 1844.",
            "citation_ids": [passage.passage_id],
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
                "When?", AnswerResult("1844", "It began in 1844.", [passage])
            )
        )
        assert result.supported
    else:
        adapter = LiteLLMSynthesis(model=model)
        result = await adapter.synthesize(SynthesisInput("When?", [passage]))
        assert result.short_answer == "1844"
    assert adapter.model is model
    assert not isinstance(adapter, LiteLLMStructuredModel)
    assert result.provider == "fake"
    assert result.model == "fake/model"
    assert result.usage == {"total_tokens": 10}
    assert result.estimated_cost_usd == 0.001
    model.complete.assert_awaited_once()
    assert model.complete.call_args.kwargs["schema_name"] == (
        "evidence_verification" if verification else "evidence_answer"
    )
