from collections import OrderedDict
from dataclasses import dataclass, replace
from typing import Literal

type NotificationType = Literal["due_soon", "due_now"]
type LoanID = str
type Time = int
type PatronID = str
type BookID = str
type NotificationID = str


@dataclass(frozen=True)
class Notification:
    id_: str
    loan_id: LoanID
    kind: NotificationType
    scheduled_time: Time
    processing_time: Time
    patron_id: PatronID
    book_id: BookID


@dataclass(frozen=True)
class Loan:
    id_: LoanID
    patron_id: PatronID
    book_id: BookID
    registered_at: Time
    due_at: Time
    due_soon: Time
    returned_at: Time | None = None


class InvalidString(Exception):
    pass


class LoanIDAlreadyExists(Exception):
    pass


class LoanDoesNotExist(Exception):
    pass


class InvalidTime(Exception):
    pass


class InvalidRegisteredAt(Exception):
    pass


class InvalidProcessingTime(Exception):
    pass


class DueDateNotificationsService:
    def __init__(self):
        self._loans: dict[LoanID, Loan] = {}
        self._notifications: OrderedDict[NotificationID, Notification] = OrderedDict()
        self._last_processed_at: Time | None = None

    def _validate_non_empty_string(self, value: str):
        if isinstance(value, str) and not value.isspace() and value != "":
            return
        raise InvalidString

    def _validate_time(self, value):
        if type(value) is int:
            return
        raise InvalidTime

    def loan_book(
        self,
        loan_id: str,
        patron_id: str,
        book_id: str,
        registered_at: Time,
        due_at: Time,
    ) -> LoanID:

        self._validate_non_empty_string(loan_id)
        self._validate_non_empty_string(patron_id)
        self._validate_non_empty_string(book_id)
        self._validate_time(registered_at)
        self._validate_time(due_at)

        if due_at <= registered_at:
            raise InvalidTime("due_at needs to be greater than registered_at")

        if loan_id in self._loans:
            raise LoanIDAlreadyExists

        self._loans[loan_id] = Loan(
            id_=loan_id,
            patron_id=patron_id,
            book_id=book_id,
            registered_at=registered_at,
            due_at=due_at,
            due_soon=due_at - 86_400,
        )
        return loan_id

    def return_book(self, loan_id: LoanID, returned_at: Time):
        self._validate_non_empty_string(loan_id)
        self._validate_time(returned_at)

        loan = self._loans.get(loan_id)
        if loan is None:
            raise LoanDoesNotExist

        if returned_at < loan.registered_at:
            raise InvalidRegisteredAt

        self._loans[loan_id] = replace(loan, returned_at=returned_at)

    def process_notifications(self, now: Time) -> list[Notification]:
        self._validate_time(now)

        if self._last_processed_at is None:
            self._last_processed_at = now
        elif now < self._last_processed_at:
            raise InvalidProcessingTime
        self._last_processed_at = now

        notifications = []
        for loan_id, loan in self._loans.items():
            if loan.returned_at is not None:
                continue

            notification_id_due_soon = f"{loan.id_}--due_soon"
            if (
                notification_id_due_soon not in self._notifications
                and loan.due_soon <= now
            ):
                n1 = Notification(
                    id_=notification_id_due_soon,
                    loan_id=loan_id,
                    kind="due_soon",
                    scheduled_time=loan.due_soon,
                    processing_time=now,
                    patron_id=loan.patron_id,
                    book_id=loan.book_id,
                )
                self._notifications[notification_id_due_soon] = n1
                notifications.append(n1)

            notification_id_due_at = f"{loan.id_}--due_at"
            if notification_id_due_at not in self._notifications and loan.due_at <= now:
                n2 = Notification(
                    id_=notification_id_due_at,
                    loan_id=loan_id,
                    kind="due_now",
                    scheduled_time=loan.due_at,
                    processing_time=now,
                    patron_id=loan.patron_id,
                    book_id=loan.book_id,
                )
                self._notifications[notification_id_due_at] = n2
                notifications.append(n2)

        notifications.sort(key=lambda n: (n.scheduled_time, n.loan_id, n.kind))
        return notifications

    def list_notifications(self) -> tuple[Notification, ...]:
        return tuple(
            sorted(
                self._notifications.values(),
                key=lambda notification: (
                    notification.scheduled_time,
                    notification.loan_id,
                    notification.kind,
                ),
            )
        )
