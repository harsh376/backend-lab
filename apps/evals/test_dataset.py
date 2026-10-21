from pathlib import Path

import pytest

from apps.evals.dataset import load_cases, select_cases

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
