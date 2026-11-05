from pathlib import Path

import pytest

from apps.evals.datasets.dataset import load_cases, select_cases

DATASET = Path(__file__).parent / "kilt-v1/dev.json"


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


@pytest.mark.parametrize("kind", ["local", "langfuse"])
def test_case_contract_does_not_depend_on_source(kind):
    from apps.evals.models import EvalCase

    record = load_cases(DATASET)[0].model_dump()
    record["source"]["kind"] = kind
    record["evidence_sets"] = []
    # Correctness scoring needs reference answers, not gold retrieval evidence.
    case = EvalCase.model_validate(record)
    assert case.evidence_sets == []
    record["accepted_answers"] = []
    with pytest.raises(ValueError, match="accepted answer"):
        EvalCase.model_validate(record)
    record["accepted_answers"] = ["answer"]
    record["evidence_sets"] = [[]]
    with pytest.raises(ValueError, match="evidence sets must not be empty"):
        EvalCase.model_validate(record)


def test_group_id_matches_local_builder_normalization():
    from apps.evals.datasets.dataset import question_group_id

    for case in load_cases(DATASET):
        assert question_group_id(case.question) == case.group_id
    assert question_group_id("Who?  WROTE it!") == question_group_id("who wrote it")


def test_select_cases_excludes_tags():
    base = load_cases(DATASET)[0]
    cases = [
        base.model_copy(update={"case_id": "a", "tags": ["nq"]}),
        base.model_copy(update={"case_id": "b", "tags": ["nq", "time_sensitive"]}),
    ]
    selected = select_cases(
        cases, limit=None, tags=["nq"], exclude_tags=["time_sensitive"]
    )
    assert [case.case_id for case in selected] == ["a"]


def test_bundled_cases_are_reviewed():
    cases = load_cases(DATASET)
    assert all(case.review is not None for case in cases)
    rejected = [case for case in cases if case.review.decision == "reject"]
    assert rejected and all("rejected" in case.tags for case in rejected)


def test_reject_review_and_rejected_tag_must_agree():
    from apps.evals.models import EvalCase

    record = load_cases(DATASET)[0].model_dump()
    record["review"] = {"decision": "reject", "reason": "x", "reviewed": "2026-11-04"}
    with pytest.raises(ValueError, match="must agree"):
        EvalCase.model_validate(record)
    record["review"]["decision"] = "keep"
    record["tags"] = [*record["tags"], "rejected"]
    with pytest.raises(ValueError, match="must agree"):
        EvalCase.model_validate(record)
