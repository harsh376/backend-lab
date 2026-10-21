import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock, call

import pytest

from apps.evals.run import evaluate_case, load_cases, select_cases

DATASET = Path(__file__).parent / "datasets/kilt-v1/dev.json"


def test_select_cases_filters_before_limit():
    base = load_cases(DATASET)[0]
    cases = [
        base.model_copy(update={"case_id": "a", "tags": ["nq"]}),
        base.model_copy(update={"case_id": "b", "tags": ["nq", "verified"]}),
        base.model_copy(update={"case_id": "c", "tags": ["nq", "verified"]}),
        base.model_copy(
            update={"case_id": "d", "tags": ["nq", "verified", "rejected"]}
        ),
    ]
    assert [
        case.case_id for case in select_cases(cases, limit=1, tags=["nq", "verified"])
    ] == ["b"]
    assert [case.case_id for case in select_cases(cases, limit=10)] == ["a", "b", "c"]
    assert select_cases(cases, case_id="c") == [cases[2]]
    with pytest.raises(ValueError, match="No eligible cases"):
        select_cases(cases, tags=["missing"])
    with pytest.raises(ValueError, match="positive"):
        select_cases(cases, limit=0)


def response(payload):
    return Mock(
        is_error=False,
        structured_content=None,
        content=[Mock(text=json.dumps(payload))],
    )


async def test_evaluate_case_polls():
    case = load_cases(DATASET)[0]
    session = Mock(
        call_tool=AsyncMock(
            side_effect=[
                response({"run_id": "run", "status": "RUNNING"}),
                response({"run_id": "run", "status": "RUNNING"}),
                response(
                    {
                        "run_id": "run",
                        "status": "COMPLETED",
                        "result": {
                            "short_answer": case.accepted_answers[0],
                            "abstained": False,
                        },
                    }
                ),
            ]
        )
    )
    result = await evaluate_case(case, session, poll_interval=0.001)
    assert result["evaluators"] == {}
    assert session.call_tool.call_args_list == [
        call("answer", {"question": case.question}),
        call("get_answer", {"run_id": "run"}),
        call("get_answer", {"run_id": "run"}),
    ]


async def test_evaluate_case_terminal_failure():
    case = load_cases(DATASET)[0]
    session = Mock(
        call_tool=AsyncMock(
            side_effect=[
                response({"run_id": "run", "status": "RUNNING"}),
                response({"run_id": "run", "status": "FAILED"}),
            ]
        )
    )
    result = await evaluate_case(case, session)
    assert result["output"]["status"] == "FAILED"
    assert result["evaluators"] == {}


async def test_evaluate_case_deadline():
    case = load_cases(DATASET)[0]

    async def slow_call(*args):
        await asyncio.sleep(10)

    session = Mock(call_tool=AsyncMock(side_effect=slow_call))
    result = await evaluate_case(case, session, timeout=0.01)
    assert result["output"] == {"run_id": None, "status": "TIMEOUT"}


async def test_rejected_case_does_not_submit():
    case = load_cases(DATASET)[0].model_copy(update={"tags": ["rejected"]})
    session = Mock(call_tool=AsyncMock())
    with pytest.raises(ValueError, match="rejected"):
        await evaluate_case(case, session)
    session.call_tool.assert_not_awaited()


async def test_remote_eval_submits_direct_workflow_request(monkeypatch):
    from argparse import Namespace

    from apps.evals import run
    from apps.evals.workflow import TASK_QUEUE, EvalRunRequest, EvalWorkflow

    cases = load_cases(DATASET)[:2]
    results = [{"case_id": case.case_id} for case in cases]
    client = Mock(execute_workflow=AsyncMock(return_value=results))
    monkeypatch.setattr(run.Client, "connect", AsyncMock(return_value=client))
    args = Namespace(timeout=30, run_name="test", case_id=None)

    assert await run._evaluate_remote(args, cases) == results
    invocation = client.execute_workflow.call_args
    assert invocation.args == (EvalWorkflow.run, EvalRunRequest(cases, timeout=30))
    assert invocation.kwargs["task_queue"] == TASK_QUEUE

    args.case_id = cases[0].case_id
    assert await run._evaluate_remote(args, cases[:1]) == results[0]
