from pathlib import Path
from unittest.mock import AsyncMock

from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.exceptions import ActivityError

from apps.evals.run import load_cases
from apps.evals.workflow import EvalRunRequest, EvalWorkflow


async def test_eval_payload_round_trip():
    cases = load_cases(Path(__file__).parent / "datasets/kilt-v1/dev.json")[:2]
    request = EvalRunRequest(
        cases,
        trace_context={"trace_id": "a" * 32, "parent_span_id": "b" * 16},
    )
    converter = pydantic_data_converter
    assert await converter.decode(
        await converter.encode([request]), [EvalRunRequest]
    ) == [request]


async def test_eval_workflow_continues_after_activity_failure(monkeypatch):
    from apps.evals import workflow as module

    execute = AsyncMock(
        side_effect=[
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
    base = load_cases(Path(__file__).parent / "datasets/kilt-v1/dev.json")[0]
    cases = [base.model_copy(update={"case_id": case_id}) for case_id in ("one", "two")]
    context = {"trace_id": "a" * 32, "parent_span_id": "b" * 16}
    result = await EvalWorkflow().run(
        EvalRunRequest(cases, timeout=10, trace_context=context)
    )
    assert result[0]["output"]["status"] == "FAILED"
    assert result[0]["evaluators"] == {}
    assert result[1]["evaluators"]["answer_correctness"]["correctness"] == 1
    for invocation in execute.call_args_list:
        assert invocation.args[0] == "evaluate_mcp_case"
        assert invocation.args[1].trace_context == context
        assert invocation.kwargs["retry_policy"].maximum_attempts == 1
        assert invocation.kwargs["start_to_close_timeout"].total_seconds() == 100
