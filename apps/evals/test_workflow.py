from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.exceptions import ActivityError, ApplicationError

from apps.evals.datasets.dataset import load_cases
from apps.evals.workflow import EvalCaseRequest, EvalRunRequest, EvalWorkflow
from backend.config import Settings


async def test_eval_payload_round_trip():
    request = EvalRunRequest(
        limit=2,
        experiment_name="BM25 baseline",
        trace_context={"trace_id": "a" * 32, "parent_span_id": "b" * 16},
        timeout_settings=Settings(timeout_answer_eval_seconds=900).timeout_snapshot(),
    )
    converter = pydantic_data_converter
    assert await converter.decode(
        await converter.encode([request]), [EvalRunRequest]
    ) == [request]
    case = load_cases(Path(__file__).parent / "datasets/kilt-v1/dev.json")[0]
    case_request = EvalCaseRequest(case, timeout_settings=request.timeout_settings)
    assert request.timeout == case_request.timeout == 900
    assert await converter.decode(
        await converter.encode([case_request]), [EvalCaseRequest]
    ) == [case_request]


@pytest.mark.parametrize("verification_enabled", [False, True])
@pytest.mark.parametrize("eval_type", ["answer", "retrieval"])
@pytest.mark.parametrize("timeout", [None, 10])
async def test_eval_workflow_continues_after_activity_failure(
    monkeypatch, eval_type, timeout, verification_enabled
):
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
            limit=2,
            verification_enabled=verification_enabled,
            **({"timeout": timeout} if timeout is not None else {}),
            trace_context=context,
            experiment_name="BM25 baseline",
            eval_type=eval_type,
            retrieval_limit=50,
        )
    )
    assert result[0]["output"]["status"] == "FAILED"
    assert result[0]["evaluators"] == {}
    assert result[0]["case"] == cases[0].model_dump(mode="json")
    assert result[1]["case"] == cases[1].model_dump(mode="json")
    assert result[1]["evaluators"]["answer_correctness"]["correctness"] == 1
    assert execute.call_args_list[0].args[0] == "load_eval_cases"
    for invocation in execute.call_args_list[1:]:
        assert invocation.args[0] == (
            "evaluate_retrieval_case"
            if eval_type == "retrieval"
            else "evaluate_mcp_case"
        )
        assert invocation.args[1].retrieval_limit == 50
        assert invocation.args[1].verification_enabled is verification_enabled
        assert invocation.args[1].eval_type == eval_type
        assert invocation.args[1].trace_context == context
        assert invocation.args[1].experiment_name == "BM25 baseline"
        assert invocation.kwargs["retry_policy"].maximum_attempts == 1
        expected_timeout = (
            (600 if eval_type == "answer" else 120) if timeout is None else timeout
        )
        assert invocation.args[1].timeout == expected_timeout
        assert (
            invocation.kwargs["start_to_close_timeout"].total_seconds()
            == expected_timeout
            + Settings.from_timeout_snapshot(None).timeout_eval_scoring_seconds
        )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"timeout": 0},
        {"timeout": 3601},
        {"limit": 0},
        {"experiment_name": ""},
        {"experiment_name": "   "},
        {"hosted_dataset": ""},
        {"hosted_dataset": "   "},
        {"eval_type": "unknown"},
        {"eval_type": "retrieval", "retrieval_limit": 0},
        {"eval_type": "retrieval", "retrieval_limit": 101},
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
