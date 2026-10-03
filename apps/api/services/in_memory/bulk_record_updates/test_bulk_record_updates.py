from dataclasses import FrozenInstanceError

import pytest

from .bulk_record_updates import (
    AlreadyExists,
    BulkRecordUpdateService,
    DoesNotExist,
    Record,
    RecordChange,
    ValidationError,
)


@pytest.fixture
def service():
    service = BulkRecordUpdateService()
    for record_id, status in [("A", "draft"), ("B", "published"), ("C", "archived")]:
        service.create_record(record_id, record_id, status)
    return service


@pytest.mark.parametrize("mode", ["partial", "atomic"])
def test_mixed_batch(service, mode):
    result = service.bulk_update_statuses(["A", "B", "C", "X", "A"], "published", mode)
    atomic = mode == "atomic"
    assert [o.record_id for o in result.outcomes] == ["A", "B", "C", "X"]
    assert [o.category for o in result.outcomes] == [
        "blocked" if atomic else "updated",
        "unchanged",
        "failed",
        "failed",
    ]
    assert [(o.previous, o.current) for o in result.outcomes] == [
        ("draft", "draft" if atomic else "published"),
        ("published", "published"),
        ("archived", "archived"),
        (None, None),
    ]
    assert (
        result.total,
        result.updated,
        result.unchanged,
        result.failed,
        result.blocked,
    ) == (4, 0 if atomic else 1, 1, 2, 1 if atomic else 0)
    assert result.mode == mode
    assert result.target_status == "published"
    for outcome in result.outcomes:
        if outcome.category in {"failed", "blocked"}:
            assert outcome.errors
    assert service.inspect_record("A").status == ("draft" if atomic else "published")
    assert service.inspect_record("B").status == "published"
    assert service.inspect_record("C").status == "archived"


@pytest.mark.parametrize("mode", ["partial", "atomic"])
@pytest.mark.parametrize("bad_id", ["", " ", None, 123, []])
def test_invalid_id_rejects_entire_request(service, mode, bad_id):
    with pytest.raises(ValidationError):
        service.bulk_update_statuses(["A", bad_id], "published", mode)
    assert service.inspect_record("A").status == "draft"


@pytest.mark.parametrize("ids", [[], ["A"]])
@pytest.mark.parametrize(
    "target,mode", [("PUBLISHED", "partial"), ("published", "bad")]
)
def test_invalid_options(service, ids, target, mode):
    with pytest.raises(ValidationError):
        service.bulk_update_statuses(ids, target, mode)
    assert service.inspect_record("A").status == "draft"


def test_atomic_duplicate_does_not_block(service):
    result = service.bulk_update_statuses(["A", "A"], "published", "atomic")
    assert (result.total, result.updated, result.failed, result.blocked) == (1, 1, 0, 0)
    assert [o.record_id for o in result.outcomes] == ["A"]
    assert service.inspect_record("A").status == "published"


def test_atomic_success_and_retry(service):
    result = service.bulk_update_statuses(["A", "B", "C"], "archived", "atomic")
    assert (result.updated, result.unchanged, result.failed, result.blocked) == (
        2,
        1,
        0,
        0,
    )
    assert all(service.inspect_record(r).status == "archived" for r in ["A", "B", "C"])
    retry = service.bulk_update_statuses(["A", "B", "C"], "archived", "atomic")
    assert (retry.updated, retry.unchanged, retry.failed, retry.blocked) == (0, 3, 0, 0)


@pytest.mark.parametrize(
    "start,target,category",
    [
        ("draft", "draft", "unchanged"),
        ("draft", "published", "updated"),
        ("draft", "archived", "updated"),
        ("published", "draft", "failed"),
        ("published", "published", "unchanged"),
        ("published", "archived", "updated"),
        ("archived", "draft", "failed"),
        ("archived", "published", "failed"),
        ("archived", "archived", "unchanged"),
    ],
)
def test_transitions(start, target, category):
    service = BulkRecordUpdateService()
    service.create_record("A", "Title", start)
    result = service.bulk_update_statuses(["A"], target)
    assert result.mode == "partial"
    assert result.outcomes[0].category == category
    assert service.inspect_record("A").status == (
        target if category == "updated" else start
    )


def test_empty_selection(service):
    result = service.bulk_update_statuses([], "published")
    assert result.outcomes == []
    assert (
        result.total,
        result.updated,
        result.unchanged,
        result.failed,
        result.blocked,
    ) == (0, 0, 0, 0, 0)


def test_creation_read_and_isolation(service):
    record_id = service.create_record(" a ", " Title ")
    assert record_id == " a "
    record = service.inspect_record(record_id)
    assert (record.id_, record.title, record.status) == (" a ", " Title ", "draft")
    service.create_record("a", " Title ")
    with pytest.raises(AlreadyExists):
        service.create_record("A", "Replacement", "archived")
    assert service.inspect_record("A").status == "draft"
    with pytest.raises(DoesNotExist):
        service.inspect_record("X")
    with pytest.raises(FrozenInstanceError):
        record.status = "archived"
    selection = ["A", "C"]
    result = service.bulk_update_statuses(selection, "published")
    selection.clear()
    result.outcomes[1].errors.clear()
    result.outcomes.clear()
    assert service.inspect_record("A").status == "published"
    assert service.inspect_record("C").status == "archived"
    assert service.bulk_update_statuses(["C"], "published").outcomes[0].errors


@pytest.mark.parametrize(
    "record_id,title,status",
    [
        (" ", "Title", "draft"),
        ("A", "", "draft"),
        ("A", "Title", "DRAFT"),
    ],
)
def test_invalid_creation(record_id, title, status):
    service = BulkRecordUpdateService()
    with pytest.raises(ValidationError):
        service.create_record(record_id, title, status)
    with pytest.raises(DoesNotExist):
        service.inspect_record("A")


def test_update_record(service):

    service.create_record("r1", "t1", "draft")

    assert service.get_record("r1") == Record(
        id_="r1", title="t1", status="draft", version=1
    )

    with pytest.raises(ValidationError, match="version mismatch"):
        service.update_record("r1", {"title": "t2"}, expected_version=2)

    # Assert no-op when same title
    assert service.update_record("r1", {"title": "t1"}, expected_version=1) is False
    assert service.get_record("r1") == Record(
        id_="r1", title="t1", status="draft", version=1
    )
    assert service.get_record_history("r1") == []

    # Assert no-op when same status
    assert service.update_record("r1", {"status": "draft"}, expected_version=1) is False
    assert service.get_record("r1") == Record(
        id_="r1", title="t1", status="draft", version=1
    )
    assert service.get_record_history("r1") == []

    # Assert title update is successful
    assert service.update_record("r1", {"title": "t2"}, expected_version=1) is True
    assert service.get_record("r1") == Record(
        id_="r1", title="t2", status="draft", version=2
    )
    assert service.get_record_history("r1") == [
        RecordChange(
            record_id="r1",
            version=2,
            before=Record(id_="r1", title="t1", status="draft", version=1),
            after=Record(id_="r1", title="t2", status="draft", version=2),
        )
    ]

    # Assert status update is successful
    assert (
        service.update_record("r1", {"status": "published"}, expected_version=2) is True
    )
    assert service.get_record("r1") == Record(
        id_="r1", title="t2", status="published", version=3
    )
    assert service.get_record_history("r1") == [
        RecordChange(
            record_id="r1",
            version=2,
            before=Record(id_="r1", title="t1", status="draft", version=1),
            after=Record(id_="r1", title="t2", status="draft", version=2),
        ),
        RecordChange(
            record_id="r1",
            version=3,
            before=Record(id_="r1", title="t2", status="draft", version=2),
            after=Record(id_="r1", title="t2", status="published", version=3),
        ),
    ]
