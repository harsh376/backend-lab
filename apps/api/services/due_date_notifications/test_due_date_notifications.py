from dataclasses import FrozenInstanceError

import pytest

from apps.api.services.due_date_notifications.due_date_notifications import (
    DueDateNotificationsService,
    InvalidProcessingTime,
    InvalidRegisteredAt,
    InvalidString,
    InvalidTime,
    LoanDoesNotExist,
    LoanIDAlreadyExists,
)

DAY = 24 * 60 * 60
REGISTERED_AT = 1_000
DUE_AT = REGISTERED_AT + 2 * DAY
DUE_SOON_AT = DUE_AT - DAY


def add_loan(
    service: DueDateNotificationsService,
    *,
    loan_id: str = "loan-1",
    patron_id: str = "patron-1",
    book_id: str = "book-1",
    registered_at: int = REGISTERED_AT,
    due_at: int = DUE_AT,
) -> None:
    service.loan_book(
        loan_id=loan_id,
        patron_id=patron_id,
        book_id=book_id,
        registered_at=registered_at,
        due_at=due_at,
    )


def test_generates_notifications_at_exact_boundaries() -> None:
    service = DueDateNotificationsService()
    add_loan(service)

    assert service.process_notifications(DUE_SOON_AT - 1) == []

    due_soon = service.process_notifications(DUE_SOON_AT)
    assert len(due_soon) == 1
    assert due_soon[0].id_ == "loan-1--due_soon"
    assert due_soon[0].kind == "due_soon"
    assert due_soon[0].scheduled_time == DUE_SOON_AT
    assert due_soon[0].processing_time == DUE_SOON_AT
    assert due_soon[0].patron_id == "patron-1"
    assert due_soon[0].book_id == "book-1"

    due_now = service.process_notifications(DUE_AT)
    assert len(due_now) == 1
    assert due_now[0].id_ == "loan-1--due_at"
    assert due_now[0].kind == "due_now"
    assert due_now[0].scheduled_time == DUE_AT
    assert due_now[0].processing_time == DUE_AT


def test_late_processing_catches_up_both_notifications() -> None:
    service = DueDateNotificationsService()
    add_loan(service)
    processed_at = DUE_AT + 500

    notifications = service.process_notifications(processed_at)

    assert [(item.kind, item.scheduled_time) for item in notifications] == [
        ("due_soon", DUE_SOON_AT),
        ("due_now", DUE_AT),
    ]
    assert all(item.processing_time == processed_at for item in notifications)


def test_processing_is_idempotent() -> None:
    service = DueDateNotificationsService()
    add_loan(service)

    first = service.process_notifications(DUE_AT)

    assert len(first) == 2
    assert service.process_notifications(DUE_AT) == []
    assert service.process_notifications(DUE_AT + 1) == []
    assert service.list_notifications() == tuple(first)


def test_notifications_are_ordered_across_loans() -> None:
    service = DueDateNotificationsService()
    add_loan(service, loan_id="b", patron_id="p-b", due_at=DUE_AT)
    add_loan(service, loan_id="a", patron_id="p-a", due_at=DUE_AT)
    add_loan(service, loan_id="earlier", due_at=DUE_AT - 100)

    notifications = service.process_notifications(DUE_AT)

    assert [(item.loan_id, item.kind) for item in notifications] == [
        ("earlier", "due_soon"),
        ("a", "due_soon"),
        ("b", "due_soon"),
        ("earlier", "due_now"),
        ("a", "due_now"),
        ("b", "due_now"),
    ]
    assert service.list_notifications() == tuple(notifications)


def test_short_loan_makes_past_reminder_eligible_immediately() -> None:
    service = DueDateNotificationsService()
    due_at = REGISTERED_AT + 60 * 60
    add_loan(service, due_at=due_at)

    notifications = service.process_notifications(REGISTERED_AT)

    assert len(notifications) == 1
    assert notifications[0].kind == "due_soon"
    assert notifications[0].scheduled_time == due_at - DAY


@pytest.mark.parametrize("returned_at", [DUE_SOON_AT - 1, DUE_SOON_AT])
def test_return_before_processing_suppresses_notifications(returned_at: int) -> None:
    service = DueDateNotificationsService()
    add_loan(service)

    service.return_book("loan-1", returned_at)

    assert service.process_notifications(DUE_AT) == []
    assert service.list_notifications() == ()


def test_return_after_first_notification_preserves_it_and_suppresses_second() -> None:
    service = DueDateNotificationsService()
    add_loan(service)
    due_soon = service.process_notifications(DUE_SOON_AT)

    service.return_book("loan-1", DUE_SOON_AT + 1)

    assert service.process_notifications(DUE_AT) == []
    assert service.list_notifications() == tuple(due_soon)


def test_return_at_registration_time_is_allowed() -> None:
    service = DueDateNotificationsService()
    add_loan(service)

    service.return_book("loan-1", REGISTERED_AT)

    assert service.process_notifications(DUE_AT) == []


def test_duplicate_loan_id_is_rejected_without_replacing_original() -> None:
    service = DueDateNotificationsService()
    add_loan(service)

    with pytest.raises(LoanIDAlreadyExists):
        add_loan(
            service,
            patron_id="replacement-patron",
            book_id="replacement-book",
        )

    notifications = service.process_notifications(DUE_SOON_AT)
    assert notifications[0].patron_id == "patron-1"
    assert notifications[0].book_id == "book-1"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("loan_id", ""),
        ("patron_id", ""),
        ("book_id", ""),
        ("loan_id", "   "),
    ],
)
def test_rejects_invalid_identifiers(field: str, value: str) -> None:
    service = DueDateNotificationsService()
    arguments = {
        "loan_id": "loan-1",
        "patron_id": "patron-1",
        "book_id": "book-1",
        field: value,
    }

    with pytest.raises(InvalidString):
        service.loan_book(
            **arguments,
            registered_at=REGISTERED_AT,
            due_at=DUE_AT,
        )


@pytest.mark.parametrize(
    ("registered_at", "due_at"),
    [
        (True, DUE_AT),
        (REGISTERED_AT, False),
        (REGISTERED_AT, REGISTERED_AT),
        (REGISTERED_AT, REGISTERED_AT - 1),
    ],
)
def test_rejects_invalid_loan_times(registered_at: int, due_at: int) -> None:
    service = DueDateNotificationsService()

    with pytest.raises(InvalidTime):
        add_loan(service, registered_at=registered_at, due_at=due_at)


def test_rejects_missing_loan_and_invalid_return_time_without_mutating_loan() -> None:
    service = DueDateNotificationsService()
    add_loan(service)

    with pytest.raises(LoanDoesNotExist):
        service.return_book("missing", REGISTERED_AT)
    with pytest.raises(InvalidRegisteredAt):
        service.return_book("loan-1", REGISTERED_AT - 1)

    assert len(service.process_notifications(DUE_AT)) == 2


def test_processing_time_must_be_an_integer_and_nondecreasing() -> None:
    service = DueDateNotificationsService()
    add_loan(service)

    with pytest.raises(InvalidTime):
        service.process_notifications(True)

    assert service.process_notifications(DUE_SOON_AT) != []
    assert service.process_notifications(DUE_SOON_AT) == []

    with pytest.raises(InvalidProcessingTime):
        service.process_notifications(DUE_SOON_AT - 1)

    assert service.process_notifications(DUE_AT) != []


def test_notification_inspection_returns_an_immutable_snapshot() -> None:
    service = DueDateNotificationsService()
    add_loan(service)
    service.process_notifications(DUE_SOON_AT)
    snapshot = service.list_notifications()

    assert isinstance(snapshot, tuple)
    with pytest.raises(FrozenInstanceError):
        snapshot[0].book_id = "changed"

    extended_snapshot = snapshot + snapshot
    assert len(extended_snapshot) == 2
    assert service.list_notifications() == snapshot
