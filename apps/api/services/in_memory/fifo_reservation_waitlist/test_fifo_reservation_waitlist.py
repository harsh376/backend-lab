from dataclasses import FrozenInstanceError

import pytest

from apps.api.services.in_memory.fifo_reservation_waitlist.fifo_reservation_waitlist import (  # noqa: E501
    FIFOReservationWaitlistService,
)


def _waiting_patron_ids(service, title_id):
    return [
        reservation.patron_id
        for reservation in service.list_state()["reservations"].values()
        if reservation.title_id == title_id and reservation.status == "WAITING"
    ]


def _reserved_patron_ids(service, title_id):
    return [
        reservation.patron_id
        for reservation in service.list_state()["reservations"].values()
        if reservation.title_id == title_id and reservation.status == "RESERVED"
    ]


def test_register_title_and_add_available_copies():
    service = FIFOReservationWaitlistService()

    assert service.register_title("book", 0) == "book"
    service.add_available_copies("book", 3)

    title = service.list_state()["titles"]["book"]
    assert title.available == 3
    assert list(title.reservation_ids) == []

    state_before_failure = service.list_state()
    with pytest.raises(Exception, match="Title already exists"):
        service.register_title("book", 10)
    assert service.list_state() == state_before_failure


@pytest.mark.parametrize("copies", [-1, True, False, 1.5, "1", None])
def test_initial_stock_must_be_a_nonnegative_integer(copies):
    service = FIFOReservationWaitlistService()

    with pytest.raises(Exception, match="Not a positive int"):
        service.register_title("book", copies)
    assert service.list_state()["titles"] == {}


@pytest.mark.parametrize("copies", [0, -1, True, False, 1.5, "1", None])
def test_added_stock_must_be_a_positive_integer(copies):
    service = FIFOReservationWaitlistService()
    service.register_title("book", 0)
    state_before_failure = service.list_state()

    with pytest.raises(Exception, match="Negative int is not allowed"):
        service.add_available_copies("book", copies)
    assert service.list_state() == state_before_failure


def test_unknown_titles_fail_without_changing_state():
    service = FIFOReservationWaitlistService()
    state_before_failure = service.list_state()

    with pytest.raises(Exception, match="Title does not exist"):
        service.add_available_copies("missing", 1)
    with pytest.raises(Exception, match="Title does not exist"):
        service.join_waitlist("missing", "alice")
    with pytest.raises(Exception, match="Title does not exist"):
        service.allocate("missing")

    assert service.list_state() == state_before_failure


def test_join_creates_unique_waiting_reservations_and_rejects_active_duplicate():
    service = FIFOReservationWaitlistService()
    service.register_title("book", 0)

    alice_id = service.join_waitlist("book", "alice")
    bob_id = service.join_waitlist("book", "bob")

    assert alice_id != bob_id
    assert _waiting_patron_ids(service, "book") == ["alice", "bob"]

    state_before_failure = service.list_state()
    with pytest.raises(Exception, match="Active reservation already exists"):
        service.join_waitlist("book", "alice")
    assert service.list_state() == state_before_failure


def test_allocation_is_explicit_and_reserves_as_many_as_available_in_fifo_order():
    service = FIFOReservationWaitlistService()
    service.register_title("book", 0)
    alice_id = service.join_waitlist("book", "alice")
    bob_id = service.join_waitlist("book", "bob")
    service.join_waitlist("book", "cara")

    service.add_available_copies("book", 2)
    assert _waiting_patron_ids(service, "book") == ["alice", "bob", "cara"]
    assert _reserved_patron_ids(service, "book") == []

    allocated = service.allocate("book")

    assert [reservation.id_ for reservation in allocated] == [alice_id, bob_id]
    assert [reservation.status for reservation in allocated] == ["RESERVED", "RESERVED"]
    assert _waiting_patron_ids(service, "book") == ["cara"]
    assert _reserved_patron_ids(service, "book") == ["alice", "bob"]
    title = service.list_state()["titles"]["book"]
    assert title.available == 0
    assert list(title.reservation_ids) == [alice_id, bob_id]


def test_repeated_allocation_is_empty_and_preserves_existing_holds():
    service = FIFOReservationWaitlistService()
    service.register_title("book", 1)
    alice_id = service.join_waitlist("book", "alice")
    service.join_waitlist("book", "bob")
    service.allocate("book")
    state_before_repeat = service.list_state()

    assert service.allocate("book") == []
    assert service.list_state() == state_before_repeat
    assert list(service.list_state()["titles"]["book"].reservation_ids) == [alice_id]


def test_cancel_waiting_is_idempotent_and_rejoin_goes_to_tail():
    service = FIFOReservationWaitlistService()
    service.register_title("book", 0)
    alice_id = service.join_waitlist("book", "alice")
    service.join_waitlist("book", "bob")

    service.cancel_request(alice_id)
    state_after_cancel = service.list_state()
    service.cancel_request(alice_id)

    assert service.list_state() == state_after_cancel
    assert state_after_cancel["reservations"][alice_id].status == "CANCELLED"
    new_alice_id = service.join_waitlist("book", "alice")
    assert new_alice_id != alice_id
    assert _waiting_patron_ids(service, "book") == ["bob", "alice"]


def test_cancel_reserved_releases_copy_only_for_next_explicit_allocation():
    service = FIFOReservationWaitlistService()
    service.register_title("book", 1)
    alice_id = service.join_waitlist("book", "alice")
    bob_id = service.join_waitlist("book", "bob")
    service.allocate("book")

    service.cancel_request(alice_id)

    title = service.list_state()["titles"]["book"]
    assert title.available == 1
    assert list(title.reservation_ids) == []
    assert service.list_state()["reservations"][bob_id].status == "WAITING"

    allocated = service.allocate("book")
    assert [reservation.id_ for reservation in allocated] == [bob_id]
    assert service.list_state()["titles"]["book"].available == 0


def test_collect_is_idempotent_and_does_not_make_copy_available():
    service = FIFOReservationWaitlistService()
    service.register_title("book", 1)
    alice_id = service.join_waitlist("book", "alice")
    service.allocate("book")

    service.collect(alice_id)
    state_after_collection = service.list_state()
    service.collect(alice_id)

    assert service.list_state() == state_after_collection
    assert state_after_collection["reservations"][alice_id].status == "COLLECTED"
    title = state_after_collection["titles"]["book"]
    assert title.available == 0
    assert list(title.reservation_ids) == []


def test_invalid_lifecycle_transitions_and_unknown_ids_preserve_state():
    service = FIFOReservationWaitlistService()
    service.register_title("book", 1)
    reserved_id = service.join_waitlist("book", "reserved")
    canceled_id = service.join_waitlist("book", "canceled")
    service.allocate("book")
    service.cancel_request(canceled_id)
    state_before_failures = service.list_state()

    with pytest.raises(Exception, match="unreserved"):
        service.collect(canceled_id)
    with pytest.raises(Exception, match="Reservation does not exist"):
        service.cancel_request(999)
    with pytest.raises(Exception, match="Reservation does not exist"):
        service.collect(999)
    assert service.list_state() == state_before_failures

    service.collect(reserved_id)
    state_after_collection = service.list_state()
    with pytest.raises(Exception, match="cancelled"):
        service.cancel_request(reserved_id)
    assert service.list_state() == state_after_collection


def test_titles_are_independent_and_patron_may_join_each_title():
    service = FIFOReservationWaitlistService()
    service.register_title("book-a", 1)
    service.register_title("book-b", 2)
    reservation_a = service.join_waitlist("book-a", "alice")
    reservation_b = service.join_waitlist("book-b", "alice")

    allocated = service.allocate("book-a")

    assert [reservation.id_ for reservation in allocated] == [reservation_a]
    state = service.list_state()
    assert state["reservations"][reservation_b].status == "WAITING"
    assert state["titles"]["book-a"].available == 0
    assert state["titles"]["book-b"].available == 2


def test_returned_state_and_allocation_results_do_not_expose_internal_state():
    service = FIFOReservationWaitlistService()
    service.register_title("book", 1)
    reservation_id = service.join_waitlist("book", "alice")
    allocated = service.allocate("book")

    allocated.clear()
    snapshot = service.list_state()
    snapshot["titles"]["book"].reservation_ids.clear()
    snapshot["reservations"].clear()

    fresh_state = service.list_state()
    assert list(fresh_state["titles"]["book"].reservation_ids) == [reservation_id]
    assert fresh_state["reservations"][reservation_id].status == "RESERVED"

    reservation = fresh_state["reservations"][reservation_id]
    with pytest.raises(FrozenInstanceError):
        reservation.status = "WAITING"
