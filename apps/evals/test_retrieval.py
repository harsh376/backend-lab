from contextlib import contextmanager
from unittest.mock import AsyncMock, Mock

import pytest

from apps.evals.dataset import load_cases
from apps.evals.evaluators.retrieval import (
    evaluate_mapk,
    evaluate_mrrk,
    summarize_retrieval,
)
from apps.evals.models import Evidence
from apps.evals.test_dataset import DATASET


@pytest.fixture
def case():
    return load_cases(DATASET)[0].model_copy(
        update={
            "tags": ["page_verified"],
            "evidence_sets": [
                [
                    Evidence(
                        wikipedia_id="a",
                        start_paragraph_id=0,
                        end_paragraph_id=0,
                    )
                ],
                [
                    Evidence(
                        wikipedia_id="b",
                        start_paragraph_id=0,
                        end_paragraph_id=0,
                    )
                ],
            ],
        }
    )


@pytest.mark.parametrize(
    "pages,k,ap,rr",
    [
        (["x", "a", "a", "b"], 3, (1 / 2 + 2 / 3) / 2, 1 / 2),
        (["a", "b"], 5, 1, 1),
        (["x", "a"], 1, 0, 0),
        (["a"], 1, 1, 1),
        ([], 5, 0, 0),
    ],
)
async def test_ranked_metrics(case, pages, k, ap, rr):
    passages = [{"wikipedia_id": page} for page in pages]
    assert (await evaluate_mapk(case, passages, k=k))["ap_at_k"] == pytest.approx(ap)
    assert (await evaluate_mrrk(case, passages, k=k))["reciprocal_rank_at_k"] == rr


async def test_unscored_cases(case):
    for evaluator, metric in [
        (evaluate_mapk, "ap_at_k"),
        (evaluate_mrrk, "reciprocal_rank_at_k"),
    ]:
        assert (await evaluator(case, None))[metric] is None
        assert (await evaluator(case.model_copy(update={"tags": []}), []))[
            metric
        ] is None
        assert (await evaluator(case.model_copy(update={"evidence_sets": []}), []))[
            metric
        ] is None
        with pytest.raises(ValueError, match="positive"):
            await evaluator(case, [], k=0)


def test_macro_average_and_counts():
    summary = summarize_retrieval(
        [
            {
                "evaluators": {
                    "retrieval_mapk": {"ap_at_k": 0.5},
                    "retrieval_mrrk": {"reciprocal_rank_at_k": 0.5},
                }
            },
            {
                "evaluators": {
                    "retrieval_mapk": {"ap_at_k": 0},
                    "retrieval_mrrk": {"reciprocal_rank_at_k": 0},
                }
            },
            {"evaluators": {}},
        ]
    )
    assert summary == {
        "map_at_k": 0.25,
        "map_at_k_count": 2,
        "mrr_at_k": 0.25,
        "mrr_at_k_count": 2,
    }


async def test_retrieval_activity_spans_and_scores(case, monkeypatch):
    from apps.evals import activities
    from apps.evals.workflow import EvalCaseRequest

    spans = {}

    @contextmanager
    def observation(name, **kwargs):
        spans[name] = Mock()
        yield spans[name]

    monkeypatch.setattr(activities, "observation", observation)
    monkeypatch.setattr(activities.telemetry, "observation", observation)
    monkeypatch.setattr(
        activities.telemetry,
        "client",
        lambda: Mock(
            update_current_span=spans["eval_case"].update,
            score_current_span=spans["eval_case"].score,
        ),
    )
    monkeypatch.setattr(activities.activity, "in_activity", lambda: True)

    monkeypatch.setattr(activities, "current_context", lambda: None)
    monkeypatch.setattr(activities.activity, "info", lambda: Mock())
    monkeypatch.setattr(
        activities,
        "EVALUATORS",
        [
            ("retrieval_mapk", evaluate_mapk, "retrieval"),
            ("retrieval_mrrk", evaluate_mrrk, "retrieval"),
        ],
    )
    output = {
        "status": "COMPLETED",
        "result": {
            "short_answer": "answer",
            "retrieved_passages": [{"wikipedia_id": page} for page in ["x", "a", "b"]],
        },
    }
    monkeypatch.setattr(
        activities,
        "_generate_answer",
        AsyncMock(
            return_value={
                "output": output,
                "evaluators": {},
            }
        ),
    )
    result = await activities.evaluate_mcp_case(EvalCaseRequest(case, retrieval_k=2))
    assert result["evaluators"]["retrieval_mapk"]["ap_at_k"] == 0.25
    assert result["evaluators"]["retrieval_mrrk"]["reciprocal_rank_at_k"] == 0.5
    assert set(spans) == {"eval_case", "retrieval_mapk", "retrieval_mrrk"}
    assert {c.kwargs["name"] for c in spans["eval_case"].score.call_args_list} == {
        "ap_at_2",
        "reciprocal_rank_at_2",
    }
