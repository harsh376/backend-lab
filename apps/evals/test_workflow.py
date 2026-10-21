from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.exceptions import ActivityError, ApplicationError

from apps.evals.dataset import load_cases
from apps.evals.workflow import EvalCaseRequest, EvalRunRequest, EvalWorkflow


async def test_eval_payload_round_trip():
    request = EvalRunRequest(
        limit=2,
        experiment_name="BM25 baseline",
        trace_context={"trace_id": "a" * 32, "parent_span_id": "b" * 16},
    )
    converter = pydantic_data_converter
    assert await converter.decode(
        await converter.encode([request]), [EvalRunRequest]
    ) == [request]
    case = load_cases(Path(__file__).parent / "datasets/kilt-v1/dev.json")[0]
    case_request = EvalCaseRequest(case)
    assert await converter.decode(
        await converter.encode([case_request]), [EvalCaseRequest]
    ) == [case_request]


async def test_eval_workflow_continues_after_activity_failure(monkeypatch):
    from apps.evals import workflow as module

    base = load_cases(Path(__file__).parent / "datasets/kilt-v1/dev.json")[0]
    cases = [base.model_copy(update={"case_id": case_id}) for case_id in ("one", "two")]
    execute = AsyncMock(
        side_effect=[
            cases,
            ActivityError(
                "activity failed",
                scheduled_event_id=1,
                started_event_id=2,
                identity="worker",
                activity_type="evaluate_mcp_case",
                activity_id="1",
                retry_state=None,
            ),
            {
                "case_id": "two",
                "evaluators": {"answer_correctness": {"correctness": 1}},
            },
        ]
    )
    monkeypatch.setattr(module.workflow, "execute_activity", execute)
    context = {"trace_id": "a" * 32, "parent_span_id": "b" * 16}
    result = await EvalWorkflow().run(
        EvalRunRequest(
            limit=2, timeout=10, trace_context=context, experiment_name="BM25 baseline"
        )
    )
    assert result[0]["output"]["status"] == "FAILED"
    assert result[0]["evaluators"] == {}
    assert result[1]["evaluators"]["answer_correctness"]["correctness"] == 1
    assert execute.call_args_list[0].args[0] == "load_eval_cases"
    for invocation in execute.call_args_list[1:]:
        assert invocation.args[0] == "evaluate_mcp_case"
        assert invocation.args[1].trace_context == context
        assert invocation.args[1].experiment_name == "BM25 baseline"
        assert invocation.kwargs["retry_policy"].maximum_attempts == 1
        assert invocation.kwargs["start_to_close_timeout"].total_seconds() == 100


@pytest.mark.parametrize(
    "kwargs",
    [
        {"timeout": 0},
        {"timeout": 3601},
        {"limit": 0},
        {"retrieval_k": 0},
        {"experiment_name": ""},
        {"experiment_name": "   "},
    ],
)
async def test_invalid_requests_fail_before_loading(monkeypatch, kwargs):
    from apps.evals import workflow as module

    execute = AsyncMock()
    monkeypatch.setattr(module.workflow, "execute_activity", execute)
    with pytest.raises(ApplicationError) as error:
        await EvalWorkflow().run(EvalRunRequest(**kwargs))
    assert error.value.non_retryable
    execute.assert_not_awaited()
