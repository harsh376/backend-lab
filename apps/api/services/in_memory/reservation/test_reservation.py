from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from threading import Barrier

import pytest

from apps.api.services.reservation.reservation import (
    Hold,
    ReservationService,
    SlotFullError,
)


def test_thread_safe():
    workers = 5
    barrier = Barrier(workers)
    service = ReservationService()
    service.create_slot(id_="slot1", start=0, end=10, capacity=1)

    def attempt():
        barrier.wait(timeout=5)
        try:
            return service.create_reservation("slot1", 5)
        except SlotFullError:
            return None

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(attempt) for _ in range(workers)]
        results = [future.result() for future in futures]

    successful = [result for result in results if result is not None]
    assert len(successful) == 1
    assert set(service.reservations) == set(successful)
    assert service.slots["slot1"].reservations == set(successful)


@pytest.fixture
def service():
    svc = ReservationService()
    svc.create_slot(id_="slot1", start=0, end=10, capacity=2)
    svc.create_slot(id_="slot2", start=10, end=20, capacity=2)
    return svc


def test_models_are_immutable(service):
    reservation_id = service.create_reservation("slot1", 0)
    hold_id = service.create_hold("slot1", expires_at=5, now=0)
    slot = service.slots["slot1"]
    reservation = service.reservations[reservation_id]
    hold = service.holds[hold_id]

    with pytest.raises(FrozenInstanceError):
        slot.capacity = 100
    with pytest.raises(FrozenInstanceError):
        reservation.slot_id = "slot2"
    with pytest.raises(FrozenInstanceError):
        hold.expires_at = 100
    with pytest.raises(AttributeError):
        slot.reservations.add(999)
    with pytest.raises(AttributeError):
        slot.holds.append(hold)


def test_earlier_slot_snapshots_keep_their_state(service):
    before = service.slots["slot1"]
    reservation_id = service.create_reservation("slot1", 0)
    service.create_hold("slot1", expires_at=5, now=0)

    assert before.reservations == frozenset()
    assert before.holds == ()
    after = service.slots["slot1"]
    assert after.reservations == {reservation_id}
    assert after.holds == (Hold(id_=1, slot_id="slot1", expires_at=5),)


def test_update_reservation_moves_between_slots(service):
    reservation_id = service.create_reservation("slot1", 0)
    before = service.reservations[reservation_id]

    assert service.update_reservation(reservation_id, "slot2", 0)

    assert before.slot_id == "slot1"
    assert service.reservations[reservation_id].slot_id == "slot2"
    assert service.slots["slot1"].reservations == frozenset()
    assert service.slots["slot2"].reservations == {reservation_id}


def test_remove_reservation_frees_capacity(service):
    first = service.create_reservation("slot1", 0)
    service.create_reservation("slot1", 0)
    assert "slot1" not in service.list_available_slots(0)

    service.remove_reservation(first)

    assert first not in service.slots["slot1"].reservations
    assert service.list_available_slots(0) == ["slot1", "slot2"]


def test_hold_expiry_and_cancel_update_slot(service):
    expiring = service.create_hold("slot1", expires_at=5, now=0)
    cancelled = service.create_hold("slot2", expires_at=50, now=0)

    service.cancel_hold(cancelled)
    assert service.slots["slot2"].holds == ()

    service.list_available_slots(5)
    assert service.slots["slot1"].holds == ()
    assert expiring not in service.holds


def test_confirm_hold_creates_reservation(service):
    hold_id = service.create_hold("slot1", expires_at=5, now=0)

    reservation_id = service.confirm_hold(hold_id, 1)

    slot = service.slots["slot1"]
    assert slot.holds == ()
    assert slot.reservations == {reservation_id}
    assert hold_id not in service.holds
