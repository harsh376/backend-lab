from dataclasses import dataclass, field
from threading import RLock

type HoldID = int
type ReservationID = int
type SlotID = str
type Time = int


class ReservationServiceError(Exception):
    """Base error for reservation service operations."""


class SlotAlreadyExistsError(ReservationServiceError):
    """A slot with the requested ID already exists."""


class InvalidSlotError(ReservationServiceError, ValueError):
    """The slot's time range or capacity is invalid."""


class SlotNotFoundError(ReservationServiceError):
    """The requested slot does not exist."""


class SlotFullError(ReservationServiceError):
    """The requested slot has no remaining capacity."""


class ReservationNotFoundError(ReservationServiceError):
    """The requested reservation does not exist."""


class HoldExpiredError(ReservationServiceError):
    """A hold cannot be created with an expiration at or before now."""


class HoldNotFoundError(ReservationServiceError):
    """The requested hold does not exist or has expired."""


@dataclass
class Hold:
    id_: HoldID
    slot_id: SlotID
    expires_at: Time


@dataclass
class Reservation:
    id_: ReservationID
    slot_id: SlotID


@dataclass
class Slot:
    id_: SlotID
    start: Time
    end: Time
    capacity: int

    reservations: set[ReservationID] = field(default_factory=set)
    holds: list[Hold] = field(default_factory=list)

    def is_full(self, now: Time) -> bool:
        return (
            len(self.reservations) + len(self._list_valid_holds(now)) >= self.capacity
        )

    def expire_holds(self, now: Time) -> None:
        self.holds = self._list_valid_holds(now)

    def _list_valid_holds(self, now: Time) -> list[Hold]:
        result = []
        for hold in self.holds:
            if now < hold.expires_at:
                result.append(hold)
        return result

    @property
    def num_reservations(self) -> int:
        return len(self.reservations)

    def remove_hold(self, hold_id: HoldID):
        self.holds = [hold for hold in self.holds if hold.id_ != hold_id]


class ReservationService:
    def __init__(self):
        self.slots: dict[SlotID, Slot] = {}
        self.reservations: dict[ReservationID, Reservation] = {}
        self.reservation_id_cursor = 0
        self.holds: dict[HoldID, Hold] = {}
        self.hold_id_cursor = 0
        self._lock = RLock()

    def create_slot(self, id_: SlotID, start: Time, end: Time, capacity: int) -> SlotID:
        with self._lock:
            if id_ in self.slots:
                raise SlotAlreadyExistsError("slot_id already exists")

            if start >= end:
                raise InvalidSlotError("start must be before end")
            if capacity < 0:
                raise InvalidSlotError("capacity must be non-negative")

            self.slots[id_] = Slot(id_, start, end, capacity)
            return id_

    def create_reservation(self, slot_id: SlotID, now: Time) -> ReservationID:
        with self._lock:
            self._expire_holds(now)
            slot = self.slots.get(slot_id)
            if slot is None:
                raise SlotNotFoundError("Slot doesn't exist!")

            if slot.is_full(now):
                raise SlotFullError("Slot is full!")

            reservation_id = self.reservation_id_cursor + 1
            self.reservations[reservation_id] = Reservation(
                id_=reservation_id,
                slot_id=slot_id,
            )
            self.reservation_id_cursor += 1
            slot.reservations.add(reservation_id)
            return reservation_id

    def remove_reservation(
        self,
        reservation_id: ReservationID,
    ) -> bool:
        with self._lock:
            reservation = self.reservations.get(reservation_id)
            if reservation is None:
                raise ReservationNotFoundError("Reservation doesn't exist!")

            reservation = self.reservations.pop(reservation_id)
            slot = self.slots[reservation.slot_id]
            slot.reservations.remove(reservation_id)
            return True

    def list_available_slots(self, now: Time) -> list[SlotID]:
        with self._lock:
            self._expire_holds(now)
            available_slots: list[tuple[Time, Time, Slot]] = []

            for _, slot in self.slots.items():
                if not slot.is_full(now):
                    available_slots.append((slot.start, slot.end, slot))

            # Sort by (start, id_)
            available_slots.sort(key=lambda item: (item[0], item[2].id_))

            result = [slot.id_ for _, _, slot in available_slots]
            return result

    def create_hold(self, slot_id: SlotID, expires_at: Time, now: Time) -> HoldID:
        with self._lock:
            self._expire_holds(now)
            slot = self.slots.get(slot_id)
            if slot is None:
                raise SlotNotFoundError("Slot doesn't exist!")

            if now >= expires_at:
                raise HoldExpiredError("Already expired")

            if slot.is_full(now):
                raise SlotFullError("Slot is full!")

            hold_id = self.hold_id_cursor + 1
            hold = Hold(
                id_=hold_id,
                slot_id=slot_id,
                expires_at=expires_at,
            )
            self.holds[hold_id] = hold
            slot.holds.append(hold)
            self.hold_id_cursor += 1
            return hold_id

    def update_reservation(
        self,
        reservation_id: ReservationID,
        new_slot_id: SlotID,
        now: Time,
    ) -> bool:
        with self._lock:
            self._expire_holds(now)
            reservation = self.reservations.get(reservation_id)
            if reservation is None:
                raise ReservationNotFoundError("Invalid reservation_id")

            new_slot = self.slots.get(new_slot_id)
            if new_slot is None:
                raise SlotNotFoundError("Invalid new_slot_id")

            if reservation.slot_id == new_slot_id:
                return True

            if new_slot.is_full(now):
                return False

            old_slot = self.slots[reservation.slot_id]
            old_slot.reservations.remove(reservation_id)
            new_slot.reservations.add(reservation_id)
            reservation.slot_id = new_slot_id
            return True

    def _expire_holds(self, now: Time) -> None:
        self.holds = {
            hid: hold for hid, hold in self.holds.items() if now < hold.expires_at
        }
        for slot in self.slots.values():
            slot.expire_holds(now)

    def confirm_hold(self, hold_id: HoldID, now: Time) -> ReservationID:
        with self._lock:
            self._expire_holds(now)
            hold = self.holds.get(hold_id)
            if hold is None:
                raise HoldNotFoundError("Hold doesn't exist")

            self.cancel_hold(hold_id)
            reservation_id = self.create_reservation(slot_id=hold.slot_id, now=now)
            return reservation_id

    def cancel_hold(self, hold_id: HoldID):
        with self._lock:
            hold = self.holds.get(hold_id)
            if hold is None:
                raise HoldNotFoundError("Hold doesn't exist")

            slot = self.slots[hold.slot_id]
            slot.remove_hold(hold_id)
            self.holds.pop(hold_id)
