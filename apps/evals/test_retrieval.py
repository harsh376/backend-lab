import json
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from apps.evals.activities import RetrievalEvalActivities
from apps.evals.datasets.dataset import load_cases
from apps.evals.evaluators.retrieval import (
    evaluate_retrieval,
    passage_recall,
    recall_at_k,
    summarize_retrieval,
)
from apps.evals.models import Evidence
from apps.evals.workflow import EvalCaseRequest
from backend.domains.kilt import KiltSearchHit
from backend.services.answer_synthesis.answer_synthesis import (
    ExtractiveSynthesisService,
    SynthesisInput,
)
from backend.services.kilt.kilt import KiltService


@pytest.fixture
def retrieval_activity(monkeypatch):
    from apps.mcp import telemetry

    monkeypatch.setattr(telemetry, "client", lambda: None)
    monkeypatch.setattr(
        telemetry.activity,
        "info",
        lambda: Mock(workflow_id="retrieval-run", workflow_run_id="execution"),
    )
    repository = Mock(corpus_version="test-index", asearch=AsyncMock(return_value=[]))
    return (
        RetrievalEvalActivities(KiltService(repository), ExtractiveSynthesisService()),
        repository,
    )


@pytest.fixture
def case():
    case = load_cases(Path(__file__).parent / "datasets/kilt-v1/dev.json")[0]

    def evidence(page):
        return Evidence(wikipedia_id=page, start_paragraph_id=0, end_paragraph_id=1)

    return case.model_copy(
        update={
            "tags": ["page_verified", "passage_verified"],
            "evidence_sets": [
                [evidence("a"), evidence("a"), evidence("b")],
                [evidence("c")],
            ],
        }
    )


def test_recall_alternatives_cutoffs_and_duplicate_pages(case):
    assert recall_at_k(case, ["x", "a", "b"], 1) == 0
    assert recall_at_k(case, ["x", "a", "b"], 2) == 0.5
    assert recall_at_k(case, ["x", "a", "b"], 3) == 1
    assert recall_at_k(case, ["c"], 5) == 1
    assert recall_at_k(case, ["a", "a"], 5) == 0.5
    assert recall_at_k(case, [], 5) == 0
    with pytest.raises(ValueError):
        recall_at_k(case, [], 0)


def test_uses_actual_candidates_and_only_scores_supported_cutoffs(case):
    result = evaluate_retrieval(
        case,
        {
            "ranked_page_ids": ["c"],
            "limit": 5,
            "corpus_version": "test-index",
        },
    )
    assert result["ranked_page_ids"] == ["c"]
    assert result["recall@5"] == 1
    assert result["recall@10"] is None
    assert result["recall@50"] is None
    assert result["scored_ks"] == [5]
    assert result["corpus_version"] == "test-index"


@pytest.mark.parametrize("update", [{"evidence_sets": []}, {"answerable": False}])
def test_inapplicable_is_unscored(case, update):
    result = evaluate_retrieval(case.model_copy(update=update), None)
    assert result["recall@5"] is None


def test_missing_candidates_is_unscored(case):
    result = evaluate_retrieval(case, None)
    assert result["recall@5"] is None


def test_empty_completed_retrieval_scores_zero(case):
    result = evaluate_retrieval(
        case,
        {
            "ranked_page_ids": [],
            "limit": 100,
            "corpus_version": "test-index",
        },
    )
    assert result["recall@5"] == result["recall@100"] == 0


def test_summary_retains_zero_and_excludes_unscored():
    results = [
        {"evaluators": {"retrieval_recall_at_k": {"recall@50": v}}}
        for v in [0, 1, None]
    ]
    summary = summarize_retrieval(results)
    assert summary["recall@50"] == 0.5
    assert summary["recall@50_count"] == 2
    assert summary["recall@5"] is None


def test_run_summary_and_response_schema_preserve_recall():
    from pydantic import TypeAdapter

    from apps.evals.evaluators.answers import summarize_answers
    from apps.evals.models import EvalRunResponse

    results = [
        {
            "evaluators": {
                "retrieval_recall_at_k": {"recall@50": recall},
                "answer_correctness": {"correctness": correctness},
            }
        }
        for recall, correctness in [(0, 1), (1, None), (None, 0)]
    ]
    summary = summarize_answers(results)
    response = TypeAdapter(EvalRunResponse).validate_python(
        {
            "run_id": "run",
            "status": "COMPLETED",
            "summary": summary,
            "retrieval_summary": summarize_retrieval(results),
        }
    )
    assert response["retrieval_summary"]["recall@50"] == 0.5
    assert response["retrieval_summary"]["recall@50_count"] == 2
    assert response["summary"]["correctness"] == 0.5

    assert response["summary"] == {"correctness": 0.5, "correctness_count": 2}


async def test_retrieval_activity_uses_production_retriever_and_bounds_output(
    monkeypatch,
    case,
    retrieval_activity,
):
    from temporalio.contrib.pydantic import pydantic_data_converter

    from apps.evals import activities

    generate = AsyncMock(side_effect=AssertionError("answer execution is forbidden"))
    judge = AsyncMock(side_effect=AssertionError("judge execution is forbidden"))
    monkeypatch.setattr(activities, "_generate_answer", generate)
    monkeypatch.setattr(activities, "evaluate_correctness", judge)
    activity, repository = retrieval_activity
    repository.asearch.return_value = [
        KiltSearchHit(
            id="c",
            wikipedia_id="c",
            title="Large article",
            paragraphs=("x" * 3_000_000,),
            score=1,
        ),
    ]
    request = EvalCaseRequest(case, eval_type="retrieval", retrieval_limit=50)
    result = await activity.evaluate(request)
    repository.asearch.assert_awaited_once_with(case.question, 50)
    assert result["output"] == {
        "status": "COMPLETED",
        "result": {
            "ranked_page_ids": ["c"],
            "limit": 50,
            "corpus_version": "test-index",
            "synthesis_service": "ExtractiveSynthesisService",
            "passage_ranker": None,
        },
    }
    scores = result["evaluators"]["retrieval_recall_at_k"]
    assert scores["recall@50"] == 1
    assert scores["recall@100"] is None
    assert scores["passage_recall@50"] == 0.5
    assert scores["passage_recall@100"] is None
    assert scores["synthesis_paragraph_counts"] == {"5": 1, "10": 1, "50": 1}
    assert result["elapsed_seconds"] >= 0
    encoded = await pydantic_data_converter.encode([result])
    assert len(encoded[0].data) < 10_000
    assert await pydantic_data_converter.decode(encoded, [dict]) == [result]
    generate.assert_not_awaited()
    judge.assert_not_awaited()


async def test_empty_retrieval_keeps_corpus_and_scores_zero(case, retrieval_activity):
    activity, _ = retrieval_activity
    result = await activity.evaluate(EvalCaseRequest(case, eval_type="retrieval"))
    assert result["output"]["result"]["corpus_version"] == "test-index"
    assert result["evaluators"]["retrieval_recall_at_k"]["recall@100"] == 0


async def test_retrieval_reports_recall_and_reference_pages_to_experiment(
    monkeypatch,
    case,
    retrieval_activity,
):
    from apps.evals import activities, experiments
    from apps.mcp import telemetry

    instance = Mock(get_current_observation_id=Mock(return_value="root"))
    monkeypatch.setattr(telemetry, "client", lambda: instance)
    monkeypatch.setattr(activities, "current_context", lambda: {"trace_id": "trace"})
    root = Mock()
    monkeypatch.setattr(experiments.trace, "get_current_span", lambda: root)
    monkeypatch.setattr(
        experiments,
        "_project_trace_url",
        lambda instance: "https://example.com/project/p/traces/trace",
    )

    @contextmanager
    def observation(*args, **kwargs):
        yield Mock()

    monkeypatch.setattr(telemetry, "observation", observation)
    activity, _ = retrieval_activity
    result = await activity.evaluate(
        EvalCaseRequest(
            case,
            eval_type="retrieval",
            experiment_name="retrieval-baseline",
        )
    )
    scores = {
        call.kwargs["name"]: call.kwargs["value"]
        for call in instance.score_current_span.call_args_list
    }
    assert scores == {
        f"{prefix}@{k}": 0
        for prefix in ("recall", "passage_recall")
        for k in (5, 10, 50, 100)
    }
    attributes = dict(call.args for call in root.set_attribute.call_args_list)
    assert attributes["langfuse.experiment.metadata.eval_type"] == "retrieval"
    assert attributes["langfuse.experiment.metadata.retrieval_limit"] == "100"
    assert "langfuse.experiment.metadata.judge_model" not in attributes
    assert json.loads(attributes["langfuse.experiment.item.expected_output"]) == [
        ["a", "b"],
        ["c"],
    ]
    assert result["trace_id"] == "trace"
    assert result["experiment_url"].endswith(result["experiment_id"])


@pytest.mark.parametrize("error", [TimeoutError, ConnectionError])
async def test_retrieval_failures_reach_workflow_without_a_zero_score(
    case,
    retrieval_activity,
    error,
):
    activity, repository = retrieval_activity
    repository.asearch.side_effect = error
    with pytest.raises(error):
        await activity.evaluate(EvalCaseRequest(case, eval_type="retrieval"))


def test_passage_recall_counts_inclusive_ranges_overlaps_and_alternatives(case):
    def evidence(page, start, end):
        return Evidence(
            wikipedia_id=page, start_paragraph_id=start, end_paragraph_id=end
        )

    case = case.model_copy(
        update={
            "evidence_sets": [
                [evidence("a", 0, 2), evidence("a", 1, 3), evidence("b", 2, 2)],
                [evidence("c", 0, 0)],
            ]
        }
    )
    a = {("a", i) for i in range(4)}
    assert passage_recall(case, a) == 0.8
    assert passage_recall(case, a | {("b", 2)}) == 1
    assert passage_recall(case, {("a", 0), ("a", 1)}) == 0.4
    assert passage_recall(case, {("c", 0)}) == 1
    assert passage_recall(case, {("b", 0), ("b", 1)}) == 0
    assert passage_recall(case, {("x", 0)}) == 0
    assert passage_recall(case, set()) == 0


@pytest.mark.parametrize(
    "update",
    [
        {"answerable": False},
        {"evidence_sets": []},
        {"tags": ["page_verified"]},
    ],
)
def test_passage_recall_requires_verified_applicable_evidence(case, update):
    assert passage_recall(case.model_copy(update=update), {("c", 0)}) is None


def test_passage_scoring_cutoffs_and_missing_synthesis_input(case):
    candidates = {
        "ranked_page_ids": ["c"],
        "limit": 5,
        "corpus_version": "test-index",
    }
    passages = {5: {("c", 0)}}
    scores = evaluate_retrieval(case, candidates, passages)
    assert scores["recall@5"] == 1
    assert scores["passage_recall@5"] == 0.5
    assert scores["passage_recall@10"] is None
    assert scores["passage_recall_reason"] is None
    assert scores["synthesis_paragraph_counts"] == {"5": 1}
    assert evaluate_retrieval(case, None)["passage_recall@5"] is None
    unverified = evaluate_retrieval(
        case.model_copy(update={"tags": []}), candidates, passages
    )
    assert unverified["recall@5"] == 1
    assert unverified["passage_recall@5"] is None
    assert "passage-verified" in unverified["passage_recall_reason"]
    historical = evaluate_retrieval(case, candidates)
    assert historical["recall@5"] == 1
    assert historical["passage_recall@5"] is None
    assert "synthesis input" in historical["passage_recall_reason"]


async def test_passage_recall_scores_prepared_synthesis_input_per_cutoff(
    case, retrieval_activity
):
    """A retrieved reference paragraph dropped by preparation earns no credit."""
    _, repository = retrieval_activity
    repository.asearch.return_value = [
        KiltSearchHit(
            id=page,
            wikipedia_id=page,
            title=page,
            paragraphs=("first", "second"),
            score=1,
        )
        for page in ["x"] * 5 + ["c"]
    ]
    prepared = []

    class FirstParagraphOnly(ExtractiveSynthesisService):
        async def prepare_input(self, data):
            prepared.append(len(data.evidences))
            paragraphs = [e.citation_paragraphs()[0] for e in data.evidences]
            return SynthesisInput(data.question, paragraphs)

    activity = RetrievalEvalActivities(KiltService(repository), FirstParagraphOnly())
    request = EvalCaseRequest(case, eval_type="retrieval", retrieval_limit=10)
    scores = (await activity.evaluate(request))["evaluators"]["retrieval_recall_at_k"]
    assert prepared == [5, 6]
    assert scores["recall@5"] == 0
    assert scores["recall@10"] == 1
    assert scores["passage_recall@5"] == 0
    assert scores["passage_recall@10"] == 0.5
    assert scores["synthesis_paragraph_counts"] == {"5": 1, "10": 2}


def test_passage_summary_retains_zero_and_excludes_unscored():
    results = [
        {"evaluators": {"retrieval_recall_at_k": {"passage_recall@5": value}}}
        for value in (0, 0.5, 1, None)
    ]
    summary = summarize_retrieval(results)
    assert summary["passage_recall@5"] == 0.5
    assert summary["passage_recall@5_count"] == 3
    assert summary["passage_recall@10"] is None
    assert summary["passage_recall@10_count"] == 0
