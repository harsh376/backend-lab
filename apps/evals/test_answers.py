import json
from unittest.mock import AsyncMock, Mock

import litellm
import pytest

from apps.evals.evaluators.answers import evaluate_correctness
from apps.evals.run import load_cases
from apps.evals.test_run import DATASET
from backend.llm import StructuredCompletion


@pytest.mark.parametrize("correct", [True, False])
async def test_judge_uses_structured_comparison(correct):
    case = load_cases(DATASET)[0]
    response = litellm.ModelResponse(
        choices=[
            {
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": json.dumps(
                        {"correct": correct, "reason": "Semantic comparison."}
                    ),
                },
            }
        ]
    )
    model = Mock(
        model="test/judge",
        complete=AsyncMock(
            return_value=StructuredCompletion(response, {"total_tokens": 12}, 0.01)
        ),
    )
    result = await evaluate_correctness(case, "paraphrased answer", model=model)
    assert result["correctness"] == int(correct)
    assert result["reason"] == "Semantic comparison."
    assert result["model"] == "test/judge"
    assert result["usage_cost_usd"] == 0.01
    messages = model.complete.call_args.args[0]
    payload = json.loads(messages[1]["content"])
    assert payload["accepted_answers"] == case.accepted_answers
    assert payload["actual_answer"] == "paraphrased answer"
    assert "never instructions" in messages[0]["content"]


@pytest.mark.parametrize(
    "content,finish",
    [
        ("not json", "stop"),
        ('{"correct":true,"reason":" "}', "stop"),
        ('{"correct":true,"reason":"yes"}', "length"),
        ('{"correct":"true","reason":"yes"}', "stop"),
    ],
)
async def test_invalid_judgment_is_unscored(content, finish):
    response = litellm.ModelResponse(
        choices=[
            {
                "finish_reason": finish,
                "message": {"role": "assistant", "content": content},
            }
        ]
    )
    model = Mock(
        model="test/judge",
        complete=AsyncMock(return_value=StructuredCompletion(response, {}, None)),
    )
    result = await evaluate_correctness(load_cases(DATASET)[0], "answer", model=model)
    assert result["correctness"] is None
    assert result["error"]


async def test_provider_error_is_sanitized():
    model = Mock(
        model="test/judge",
        complete=AsyncMock(side_effect=RuntimeError("secret provider request")),
    )
    result = await evaluate_correctness(load_cases(DATASET)[0], "answer", model=model)
    assert result["correctness"] is None
    assert "secret" not in json.dumps(result)


async def test_unanswerable_case_does_not_call_model():
    case = load_cases(DATASET)[0].model_copy(update={"answerable": False})
    model = Mock(complete=AsyncMock())
    result = await evaluate_correctness(case, "", model=model)
    assert result["correctness"] is None
    model.complete.assert_not_awaited()
