from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from apps.evals import activities
from apps.evals.dataset import load_cases
from apps.evals.workflow import EvalCaseRequest, EvalRunRequest


@pytest.mark.parametrize(
    "status,score,enabled",
    [("COMPLETED", 1, True), ("TIMEOUT", None, True), ("COMPLETED", 0, False)],
)
@pytest.mark.parametrize("evaluator_count", [1, 2])
async def test_eval_trace(monkeypatch, status, score, enabled, evaluator_count):
    case = load_cases(Path(__file__).parent / "datasets/kilt-v1/dev.json")[0]
    span = Mock()
    observed = {}
    children = []

    @contextmanager
    def observation(name, **kwargs):
        if name == "eval_case":
            observed.update(name=name, **kwargs)
            yield span if enabled else None
        else:
            child = Mock()
            children.append((name, child))
            yield child if enabled else None

    monkeypatch.setattr(activities, "observation", observation)
    monkeypatch.setattr(activities.telemetry, "observation", observation)
    instance = Mock(update_current_span=span.update, score_current_span=span.score)
    monkeypatch.setattr(
        activities.telemetry, "client", lambda: instance if enabled else None
    )
    monkeypatch.setattr(activities.activity, "in_activity", lambda: True)

    monkeypatch.setattr(
        activities,
        "current_context",
        lambda: {"trace_id": "eval-trace"} if enabled else None,
    )
    monkeypatch.setattr(
        activities.activity,
        "info",
        lambda: Mock(
            workflow_id="eval-run",
            workflow_run_id="temporal-run",
            activity_id="case-1",
            attempt=1,
        ),
    )
    result = {
        "case_id": case.case_id,
        "output": {
            "run_id": "answer-run",
            "status": status,
            "result": {
                "short_answer": "answer",
                "abstained": False,
            },
        },
        "evaluators": {},
    }

    judge = AsyncMock(return_value={"correctness": score})
    second = AsyncMock(return_value={"quality": score})
    evaluators = [("answer_correctness", judge, "answer")]
    if evaluator_count == 2:
        evaluators.append(("additional_quality", second, "answer"))
    monkeypatch.setattr(activities, "EVALUATORS", evaluators)

    evaluate = AsyncMock(return_value=result)
    monkeypatch.setattr(activities, "_generate_answer", evaluate)
    parent_context = {"trace_id": "a" * 32, "parent_span_id": "b" * 16}
    assert (
        await activities.evaluate_mcp_case(
            EvalCaseRequest(case, trace_context=parent_context)
        )
        == result
    )
    assert observed["trace_context"] == parent_context
    evaluate.assert_awaited_once_with(
        case, 120, {"trace_id": "eval-trace"} if enabled else None
    )
    if status == "COMPLETED":
        assert [name for name, _ in children] == [entry[0] for entry in evaluators]
        judge.assert_awaited_once_with(case, "answer", abstained=False)
    else:
        assert children == []
        judge.assert_not_awaited()
    assert result["evaluators"]["answer_correctness"].get("correctness") == score
    if evaluator_count == 2:
        assert result["evaluators"]["additional_quality"].get("quality") == score
        if status == "COMPLETED":
            second.assert_awaited_once_with(case, "answer", abstained=False)
        else:
            second.assert_not_awaited()
    assert observed["session_id"] == "eval-run"
    assert observed["input"]["accepted_pages"] == sorted(
        {
            evidence.wikipedia_id
            for evidence_set in case.evidence_sets
            for evidence in evidence_set
        }
    )
    assert observed["metadata"]["case_id"] == case.case_id
    if enabled:
        assert result["trace_id"] == "eval-trace"
        output = next(
            c.kwargs["output"]
            for c in span.update.call_args_list
            if "output" in c.kwargs
        )
        assert output["evaluators"]["answer_correctness"].get("correctness") == score
        assert "answers" not in output["evaluators"]
        if evaluator_count == 2:
            assert output["evaluators"]["additional_quality"].get("quality") == score
        assert output["case_id"] == result["case_id"]
        assert span.update.call_args_list[0].kwargs["metadata"] == {
            "answer_id": "answer-run",
            "answer_trace_id": None,
        }
        if score is not None:
            assert span.score.call_count == evaluator_count
            span.score.assert_any_call(
                name="correctness", value=score, data_type="NUMERIC", comment=None
            )
        else:
            span.score.assert_not_called()
            assert any(
                c.kwargs.get("level") == "ERROR" for c in span.update.call_args_list
            )
    else:
        span.update.assert_not_called()


async def test_direct_answer_has_separate_linked_trace(monkeypatch):
    from apps.mcp.agent.models import AnswerResult

    case = load_cases(Path(__file__).parent / "datasets/kilt-v1/dev.json")[0]
    monkeypatch.setattr(
        activities.activity,
        "info",
        lambda: Mock(
            workflow_id="eval-run", workflow_run_id="execution", activity_id="1"
        ),
    )
    observed = {}

    @contextmanager
    def observation(name, **kwargs):
        observed.update(name=name, **kwargs)
        yield Mock()

    monkeypatch.setattr(activities, "observation", observation)
    monkeypatch.setattr(
        activities,
        "current_context",
        lambda: {"trace_id": "answer-trace", "parent_span_id": "answer-span"},
    )
    client = Mock(
        start_workflow=AsyncMock(
            return_value=Mock(
                result=AsyncMock(return_value=AnswerResult("answer", "explanation"))
            )
        )
    )
    monkeypatch.setattr(activities.Client, "connect", AsyncMock(return_value=client))
    result = await activities._generate_answer(case, 10, {"trace_id": "eval-trace"})
    invocation = client.start_workflow.call_args
    assert invocation.args[0] == activities.AnswerWorkflow.run
    request = invocation.args[1]
    assert request.question == case.question
    assert request.trace_context["trace_id"] == "answer-trace"
    assert invocation.kwargs["task_queue"] == "kilt-answers"
    assert observed["name"] == "answer"
    assert observed["trace_context"]["trace_id"] != "eval-trace"
    assert observed["metadata"]["eval_trace_id"] == "eval-trace"
    assert result["answer_trace_id"] == observed["trace_context"]["trace_id"]
    assert result["output"]["status"] == "COMPLETED"


async def test_direct_answer_timeout(monkeypatch):
    case = load_cases(Path(__file__).parent / "datasets/kilt-v1/dev.json")[0]
    monkeypatch.setattr(
        activities.activity,
        "info",
        lambda: Mock(
            workflow_id="eval-run", workflow_run_id="execution", activity_id="1"
        ),
    )

    @contextmanager
    def observation(*args, **kwargs):
        yield None

    monkeypatch.setattr(activities, "observation", observation)
    monkeypatch.setattr(activities, "current_context", lambda: None)
    client = Mock(
        start_workflow=AsyncMock(
            return_value=Mock(result=AsyncMock(side_effect=TimeoutError))
        )
    )
    monkeypatch.setattr(activities.Client, "connect", AsyncMock(return_value=client))
    result = await activities._generate_answer(case, 10, None)
    assert result["output"]["status"] == "TIMEOUT"
    assert result["output"]["run_id"].startswith("kilt-answer-eval-")
    assert (
        client.start_workflow.call_args.kwargs["execution_timeout"].total_seconds()
        == 10
    )


async def test_decorated_evaluators_are_direct_children(monkeypatch):
    from langfuse import Langfuse
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    exporter = InMemorySpanExporter()
    instance = Langfuse(
        public_key="pk-lf-eval-helper-test",
        secret_key="sk-lf-test",
        tracer_provider=TracerProvider(),
        span_exporter=exporter,
    )
    monkeypatch.setattr(activities.telemetry, "client", lambda: instance)
    monkeypatch.setattr(
        activities.activity, "info", lambda: Mock(workflow_id="eval-run")
    )
    case = load_cases(Path(__file__).parent / "datasets/kilt-v1/dev.json")[0]
    monkeypatch.setattr(
        activities,
        "_generate_answer",
        AsyncMock(
            return_value={
                "output": {"status": "COMPLETED", "result": {"short_answer": "answer"}},
                "evaluators": {},
            }
        ),
    )
    monkeypatch.setattr(
        activities,
        "EVALUATORS",
        [
            (
                "answer_correctness",
                AsyncMock(return_value={"correctness": 1}),
                "answer",
            ),
            ("retrieval_mapk", AsyncMock(return_value={"ap_at_k": 0.5}), "retrieval"),
        ],
    )
    try:
        result = await activities.evaluate_mcp_case(EvalCaseRequest(case))
        instance.flush()
        spans = exporter.get_finished_spans()
        assert {s.name for s in spans} == {
            "eval_case",
            "answer_correctness",
            "retrieval_mapk",
        }
        root = next(s for s in spans if s.name == "eval_case")
        for child in (s for s in spans if s.name != "eval_case"):
            assert child.parent.span_id == root.context.span_id
            assert child.context.trace_id == root.context.trace_id
        assert result["trace_id"] == format(root.context.trace_id, "032x")
    finally:
        instance.shutdown()


@pytest.mark.parametrize("tags", [["page_verified"], []])
async def test_load_eval_cases_selects_on_worker(tags, monkeypatch):
    from apps.evals.dataset import select_cases

    monkeypatch.setattr(
        activities.activity, "info", lambda: Mock(workflow_id="eval-run")
    )
    expected = select_cases(
        load_cases(Path(__file__).parent / "datasets/kilt-v1/dev.json"),
        limit=3,
        tags=tags,
    )
    assert await activities.load_eval_cases(EvalRunRequest(tags=tags)) == expected


async def test_load_eval_cases_no_matches_fails_without_retry(monkeypatch):
    from temporalio.exceptions import ApplicationError

    monkeypatch.setattr(
        activities.activity, "info", lambda: Mock(workflow_id="eval-run")
    )
    with pytest.raises(ApplicationError) as error:
        await activities.load_eval_cases(EvalRunRequest(case_id="missing"))
    assert error.value.non_retryable


async def test_load_eval_cases_observes_selection(monkeypatch):
    span = Mock()
    observed = {}

    @contextmanager
    def observation(name, **kwargs):
        observed.update(name=name, **kwargs)
        yield span

    monkeypatch.setattr(activities.telemetry, "observation", observation)
    monkeypatch.setattr(
        activities.activity, "info", lambda: Mock(workflow_id="eval-run")
    )
    parent = {"trace_id": "a" * 32, "parent_span_id": "b" * 16}
    cases = await activities.load_eval_cases(EvalRunRequest(trace_context=parent))
    assert observed["name"] == "load_eval_cases"
    assert observed["trace_context"] == parent
    assert observed["session_id"] == "eval-run"
    assert observed["input"] == {"case_id": None, "limit": 3, "tags": ["page_verified"]}
    span.update.assert_called_once_with(
        output={
            "count": 3,
            "case_ids": [case.case_id for case in cases],
        }
    )
