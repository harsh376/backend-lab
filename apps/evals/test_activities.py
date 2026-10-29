from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from apps.evals import activities
from apps.evals.datasets.dataset import load_cases
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
                "usage_cost_usd": 0.0,
            },
        },
        "evaluators": {},
    }

    judge = AsyncMock(return_value={"correctness": score})
    second = AsyncMock(return_value={"correctness": score})
    evaluators = [("answer_correctness", judge)]
    if evaluator_count == 2:
        evaluators.append(("additional_quality", second))
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
    assert observed["trace_context"] != parent_context
    assert "parent_span_id" not in observed["trace_context"]
    evaluate.assert_awaited_once_with(
        case,
        600,
        {"trace_id": "eval-trace"} if enabled else None,
        None,
        verification_enabled=True,
    )
    assert [name for name, _ in children] == [entry[0] for entry in evaluators]
    judge.assert_awaited_once_with(case, result["output"])
    assert result["evaluators"]["answer_correctness"].get("correctness") == score
    if evaluator_count == 2:
        assert result["evaluators"]["additional_quality"].get("correctness") == score
        second.assert_awaited_once_with(case, result["output"])
    assert "answer_cost_usd" not in result
    assert observed["session_id"] == "eval-run"
    assert observed["input"] == case.model_dump(mode="json")
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
            assert (
                output["evaluators"]["additional_quality"].get("correctness") == score
            )
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


@pytest.mark.parametrize("verification_enabled", [False, True])
async def test_direct_answer_continues_experiment_trace(
    monkeypatch, verification_enabled
):
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
    result = await activities._generate_answer(
        case, 10, {"trace_id": "eval-trace"}, verification_enabled=verification_enabled
    )
    invocation = client.start_workflow.call_args
    assert invocation.args[0] == activities.AnswerWorkflow.run
    request = invocation.args[1]
    assert request.question == case.question
    assert request.limit == 10
    assert request.verification_enabled is verification_enabled
    assert request.trace_context["trace_id"] == "answer-trace"
    assert invocation.kwargs["task_queue"] == "kilt-answers"
    assert observed["name"] == "answer"
    assert observed["trace_context"]["trace_id"] == "eval-trace"
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


@pytest.mark.parametrize("experiment_name", [None, "BM25 baseline"])
@pytest.mark.parametrize("hosted", [False, True])
async def test_decorated_evaluators_are_direct_children(
    monkeypatch, experiment_name, hosted
):
    from langfuse import Langfuse
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    exporter = InMemorySpanExporter()
    instance = Langfuse(
        public_key=f"pk-lf-eval-helper-test-{experiment_name or 'default'}-{hosted}",
        secret_key="sk-lf-test",
        tracer_provider=TracerProvider(),
        span_exporter=exporter,
        httpx_client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200, json={"successes": [], "errors": []}
                )
            )
        ),
    )
    monkeypatch.setattr(activities.telemetry, "client", lambda: instance)
    monkeypatch.setattr(
        instance, "get_trace_url", lambda **kw: "https://example.com/project/p/traces/t"
    )
    monkeypatch.setattr(
        activities.activity,
        "info",
        lambda: Mock(workflow_id="eval-run", workflow_run_id="execution"),
    )
    case = load_cases(Path(__file__).parent / "datasets/kilt-v1/dev.json")[0]
    if hosted:
        case.source = case.source.model_copy(
            update={
                "kind": "langfuse",
                "dataset_id": "hosted-dataset",
                "dataset": "errors",
                "record_id": "hosted-item",
                "version": "2026-10-22T00:00:00+00:00",
            }
        )
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
            ),
            ("additional_quality", AsyncMock(return_value={"correctness": 0.5})),
        ],
    )
    try:
        result = await activities.evaluate_mcp_case(
            EvalCaseRequest(case, experiment_name=experiment_name)
        )
        instance.flush()
        spans = exporter.get_finished_spans()
        assert {s.name for s in spans} == {
            "eval_case",
            "answer_correctness",
            "additional_quality",
        }
        root = next(s for s in spans if s.name == "eval_case")
        # SDK trace-id overrides use a synthetic, unexported parent.
        assert root.parent is None or root.parent.span_id not in {
            s.context.span_id for s in spans
        }
        root_id = format(root.context.span_id, "016x")
        expected_name = experiment_name or (
            f"eval-run/{activities.activity.info().workflow_run_id}"
        )
        assert root.attributes["langfuse.experiment.name"] == expected_name
        # A local label must not masquerade as a hosted dataset ID: the UI
        # uses that attribute to turn input cells into dataset-item links.
        if hosted:
            assert root.attributes["langfuse.experiment.dataset.id"] == "hosted-dataset"
            assert "langfuse.experiment.metadata.local_dataset" not in root.attributes
        else:
            assert "langfuse.experiment.dataset.id" not in root.attributes
            assert (
                root.attributes["langfuse.experiment.metadata.local_dataset"]
                == "kilt-v1/dev"
            )
        item_id = "hosted-item" if hosted else case.case_id
        assert root.attributes["langfuse.experiment.item.id"] == item_id
        assert (
            root.attributes["langfuse.experiment.item.root_observation_id"] == root_id
        )
        assert result["experiment_url"] == (
            "https://example.com/project/p/experiments/results?baseline="
            + result["experiment_id"]
        )
        for child in (s for s in spans if s.name != "eval_case"):
            assert child.attributes["langfuse.experiment.name"] == expected_name
            if hosted:
                assert (
                    child.attributes["langfuse.experiment.dataset.id"]
                    == "hosted-dataset"
                )
            else:
                assert "langfuse.experiment.dataset.id" not in child.attributes
            assert child.attributes["langfuse.experiment.id"] == result["experiment_id"]
            assert child.attributes["langfuse.experiment.item.id"] == item_id
            assert (
                child.attributes["langfuse.experiment.item.root_observation_id"]
                == root_id
            )
            assert "langfuse.experiment.metadata.retrieval_k" not in child.attributes
            assert child.parent.span_id == root.context.span_id
            assert child.context.trace_id == root.context.trace_id
        assert result["trace_id"] == format(root.context.trace_id, "032x")
    finally:
        instance.shutdown()


@pytest.mark.parametrize("tags", [["page_verified"], []])
@pytest.mark.parametrize("eval_type", ["answer", "retrieval"])
async def test_load_eval_cases_selects_on_worker(tags, monkeypatch, eval_type):
    from apps.evals.datasets.dataset import select_cases

    monkeypatch.setattr(
        activities.activity, "info", lambda: Mock(workflow_id="eval-run")
    )
    expected = select_cases(
        load_cases(Path(__file__).parent / "datasets/kilt-v1/dev.json"),
        limit=3,
        tags=tags,
    )
    assert (
        await activities.load_eval_cases(EvalRunRequest(tags=tags, eval_type=eval_type))
        == expected
    )


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


def test_cost_fields_are_not_emitted_as_scores(monkeypatch):
    instance = Mock()
    monkeypatch.setattr(activities.telemetry, "client", lambda: instance)
    activities._record_evaluation(
        {
            "output": {"status": "COMPLETED"},
            "answer_cost_usd": 0.03,
            "evaluators": {
                "answer_correctness": {
                    "correctness": 1,
                    "judge_cost_usd": 0.002,
                    "usage_cost_usd": 0.002,
                    "answer_cost_usd": 0.03,
                }
            },
        }
    )
    scores = {
        call.kwargs["name"]: call.kwargs["value"]
        for call in instance.score_current_span.call_args_list
    }
    assert scores == {"correctness": 1}
    assert all(
        "cost_details" not in call.kwargs
        for call in instance.update_current_span.call_args_list
    )


@pytest.mark.parametrize("status", ["COMPLETED", "TIMEOUT", "FAILED"])
async def test_e2e_only_scores_correctness(monkeypatch, status):
    case = load_cases(Path(__file__).parent / "datasets/kilt-v1/dev.json")[0]
    instance = Mock()
    monkeypatch.setattr(activities.telemetry, "client", lambda: instance)
    judge = AsyncMock(return_value={"correctness": 1})
    monkeypatch.setattr(activities, "evaluate_correctness", judge)

    async def evaluate_one(case, output, name, evaluator):
        return await evaluator(case, output)

    monkeypatch.setattr(activities, "_evaluate_one", evaluate_one)
    result = {
        "output": {"status": status, "result": {"short_answer": "answer"}},
        "evaluators": {},
    }
    from copy import deepcopy

    original = deepcopy(result)
    judgments = await activities._run_evaluators(case, result["output"])
    assert result == original
    result["evaluators"] = judgments
    assert set(judgments) == {"answer_correctness"}
    if status == "COMPLETED":
        judge.assert_awaited_once_with(case, "answer", abstained=False)
    else:
        judge.assert_not_awaited()
    activities._record_evaluation(result)
    if status != "COMPLETED":
        assert "correctness" not in result["evaluators"]["answer_correctness"]
    scores = {
        c.kwargs["name"]: c.kwargs["value"]
        for c in instance.score_current_span.call_args_list
    }
    expected = {}
    if status == "COMPLETED":
        expected["correctness"] = 1
    assert scores == expected


async def test_generate_answer_exposes_candidates_in_span_output(monkeypatch):
    from apps.mcp.agent.models import AnswerResult, ArticleCandidates

    monkeypatch.setattr(
        activities.activity,
        "info",
        lambda: Mock(
            workflow_id="eval-run",
            workflow_run_id="execution",
            activity_id="1",
        ),
    )
    span = Mock()

    @contextmanager
    def observation(*args, **kwargs):
        yield span

    monkeypatch.setattr(activities, "observation", observation)
    monkeypatch.setattr(activities, "current_context", lambda: None)
    candidates = ArticleCandidates(["123", "456"], 5, "snapshot")
    answer = AnswerResult(
        "", "No answer", abstained=True, article_candidates=candidates
    )
    client = Mock(
        start_workflow=AsyncMock(
            return_value=Mock(result=AsyncMock(return_value=answer))
        )
    )
    monkeypatch.setattr(activities.Client, "connect", AsyncMock(return_value=client))
    case = load_cases(Path(__file__).parent / "datasets/kilt-v1/dev.json")[0]
    result = await activities._generate_answer(case, 10, None)
    expected = {
        "ranked_page_ids": ["123", "456"],
        "limit": 5,
        "corpus_version": "snapshot",
    }
    assert result["output"]["result"]["article_candidates"] == expected
    assert (
        span.update.call_args.kwargs["output"]["result"]["article_candidates"]
        == expected
    )
