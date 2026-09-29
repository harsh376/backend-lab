"""
- join a book's waitlist
- cancel their request

"""

from collections import OrderedDict, deque
from copy import deepcopy
from dataclasses import dataclass, field, replace
from itertools import count
from typing import Literal

type ReservationID = int
type ReservationStatus = Literal["WAITING", "RESERVED", "COLLECTED", "CANCELLED"]


@dataclass(frozen=True)
class Title:
    id_: str
    available: int
    reservation_ids: deque[ReservationID] = field(default_factory=deque)


@dataclass(frozen=True)
class Reservation:
    id_: ReservationID
    title_id: str
    patron_id: str
    status: ReservationStatus


class FIFOReservationWaitlistService:
    def __init__(self):
        self.titles: dict[str, Title] = {}

        self.reservation_sequence = count()
        self.reservations: OrderedDict[ReservationID, Reservation] = OrderedDict()

    def _validate_non_empty_string(self, value: str):
        if not isinstance(value, str) or value.isspace() or value == "":
            raise Exception("Not a string")

    def _validate_gte_zero_integer(self, value: int):
        if type(value) is not int or value < 0:
            raise Exception("Not a positive int")

    def _validate_positive_integer(self, value: int):
        if type(value) is not int or value <= 0:
            raise Exception("Negative int is not allowed")

    def register_title(self, title_id: str, copies: int):
        self._validate_non_empty_string(title_id)
        self._validate_gte_zero_integer(copies)

        if title_id in self.titles:
            raise Exception("Title already exists")

        self.titles[title_id] = Title(
            id_=title_id,
            available=copies,
        )
        return title_id

    def add_available_copies(self, title_id: str, copies: int):
        self._validate_non_empty_string(title_id)
        self._validate_positive_integer(copies)

        title = self.titles.get(title_id)
        if title is None:
            raise Exception("Title does not exist")

        new_available = title.available + copies
        self.titles[title_id] = replace(title, available=new_available)

    def allocate(self, title_id: str) -> list[Reservation]:
        self._validate_non_empty_string(title_id)

        title = self.titles.get(title_id)
        if title is None:
            raise Exception("Title does not exist")

        waiting_reservations: deque[Reservation] = deque()
        for _, r in self.reservations.items():
            if r.title_id != title_id:
                continue

            if r.status == "WAITING":
                waiting_reservations.append(r)

        upgraded_reservation_ids: deque[ReservationID] = deque()
        available = title.available
        while available > 0 and waiting_reservations:
            waiting_reservation = waiting_reservations.popleft()
            upgraded_reservation_ids.append(waiting_reservation.id_)
            available -= 1

        self.titles[title_id] = replace(
            title,
            available=available,
            reservation_ids=title.reservation_ids + upgraded_reservation_ids,
        )
        result: list[Reservation] = []
        for r_id, _ in self.reservations.items():
            if r_id in upgraded_reservation_ids:
                self.reservations[r_id] = replace(
                    self.reservations[r_id], status="RESERVED"
                )
                result.append(self.reservations[r_id])
        return result

    def join_waitlist(self, title_id: str, patron_id: str) -> ReservationID:
        self._validate_non_empty_string(title_id)
        self._validate_non_empty_string(patron_id)

        title = self.titles.get(title_id)
        if title is None:
            raise Exception("Title does not exist")

        for _, reservation in self.reservations.items():
            if (
                reservation.patron_id == patron_id
                and reservation.title_id == title_id
                and reservation.status in ("WAITING", "RESERVED")
            ):
                raise Exception("Active reservation already exists")

        new_reservation_id = next(self.reservation_sequence)
        self.reservations[new_reservation_id] = Reservation(
            id_=new_reservation_id,
            title_id=title_id,
            patron_id=patron_id,
            status="WAITING",
        )
        return new_reservation_id

    def cancel_request(self, reservation_id: ReservationID):
        if type(reservation_id) is not int:
            raise Exception("Invalid reservation_id")

        reservation = self.reservations.get(reservation_id)
        if reservation is None:
            raise Exception("Reservation does not exist")

        if reservation.status == "CANCELLED":
            return

        if reservation.status == "WAITING":
            self.reservations[reservation_id] = replace(reservation, status="CANCELLED")
            return

        if reservation.status == "RESERVED":
            self.reservations[reservation_id] = replace(reservation, status="CANCELLED")
            title_id = reservation.title_id
            title = self.titles[title_id]
            title_reservations = title.reservation_ids
            title_reservations.remove(reservation_id)
            self.titles[reservation.title_id] = replace(
                title,
                reservation_ids=title_reservations,
                available=title.available + 1,
            )
            return

        raise Exception(
            "Reservation must be (WAITING|RESERVED) state in order to be cancelled"
        )

    def collect(self, reservation_id: ReservationID):
        if type(reservation_id) is not int:
            raise Exception("Invalid reservation_id")

        reservation = self.reservations.get(reservation_id)
        if reservation is None:
            raise Exception("Reservation does not exist")

        if reservation.status == "COLLECTED":
            return

        if reservation.status != "RESERVED":
            raise Exception("Can't collect unreserved book")

        self.reservations[reservation_id] = replace(reservation, status="COLLECTED")

        title = self.titles[reservation.title_id]
        new_reservation_ids = title.reservation_ids
        new_reservation_ids.remove(reservation_id)
        self.titles[reservation.title_id] = replace(
            self.titles[reservation.title_id], reservation_ids=new_reservation_ids
        )

    def list_state(self) -> dict:
        return deepcopy(
            {
                "titles": self.titles,
                "reservations": self.reservations,
            }
        )
