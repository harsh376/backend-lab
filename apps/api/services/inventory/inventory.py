from collections.abc import Hashable
from copy import deepcopy
from dataclasses import dataclass
from itertools import count
from typing import Literal

type ProductID = str
type RequestType = Literal["RESERVE", "COMMIT", "RELEASE"]
type ReservationStatus = Literal["ACTIVE", "COMMITTED", "RELEASED"]


@dataclass
class Stock:
    id_: ProductID
    on_hand: int
    reserved: int

    @property
    def available(self) -> int:
        return self.on_hand - self.reserved


@dataclass
class Reservation:
    id_: int
    request_id: str
    items: dict[ProductID, int]
    status: ReservationStatus


@dataclass
class Request:
    id_: str
    type_: RequestType
    payload: Hashable
    result: Reservation


class InventoryService:
    def __init__(self) -> None:
        self.stock: dict[ProductID, Stock] = {}
        self.reservation_sequence = count()

        # Preserve successful response snapshots independently of live reservations.
        self.requests: dict[str, Request] = {}
        self.reservations: dict[int, Reservation] = {}

    def receive_stock(self, product_id: ProductID, quantity: int) -> Stock:
        self._validate_id(product_id, "product_id")
        self._validate_quantity(quantity)

        product = self.stock.get(product_id)
        if product is None:
            self.stock[product_id] = Stock(
                id_=product_id,
                on_hand=quantity,
                reserved=0,
            )
        else:
            self.stock[product_id].on_hand += quantity
        return deepcopy(self.stock[product_id])

    def get_stock(self, product_id: ProductID) -> Stock | None:
        stock = self.stock.get(product_id)
        return deepcopy(stock) if stock is not None else None

    def reserve(self, items: dict[ProductID, int], request_id: str) -> Reservation:
        self._validate_id(request_id, "request_id")
        # Dict order is irrelevant to request identity.
        payload = frozenset(items.items())
        cached_result = self._replay_request(request_id, "RESERVE", payload)
        if cached_result is not None:
            return cached_result

        validated_items = self._validate_items(items)

        reservation_id = next(self.reservation_sequence)
        new_reservation = Reservation(
            id_=reservation_id,
            request_id=request_id,
            items=validated_items,
            status="ACTIVE",
        )
        # Update state
        for product_id, qty in validated_items.items():
            stock = self.stock[product_id]
            stock.reserved += qty
        self.reservations[reservation_id] = new_reservation
        return self._record_request(request_id, "RESERVE", payload, new_reservation)

    def commit(self, reservation_id: int, request_id: str) -> Reservation:
        self._validate_id(request_id, "request_id")
        cached_result = self._replay_request(request_id, "COMMIT", reservation_id)
        if cached_result is not None:
            return cached_result

        reservation = self.reservations.get(reservation_id)
        if not reservation:
            raise Exception("Invalid reservation_id")

        if reservation.status == "RELEASED":
            raise Exception("Reservation has been released")

        if reservation.status == "ACTIVE":
            for product_id, quantity in reservation.items.items():
                stock = self.stock[product_id]
                stock.reserved -= quantity
                stock.on_hand -= quantity
            reservation.status = "COMMITTED"

        # Successful no-ops also claim their request IDs.
        return self._record_request(request_id, "COMMIT", reservation_id, reservation)

    def release(self, reservation_id: int, request_id: str) -> Reservation:
        self._validate_id(request_id, "request_id")
        cached_result = self._replay_request(request_id, "RELEASE", reservation_id)
        if cached_result is not None:
            return cached_result

        reservation = self.reservations.get(reservation_id)
        if reservation is None:
            raise Exception("Reservation doesn't exist")

        if reservation.status == "COMMITTED":
            raise Exception("Reservation has already been committed")

        if reservation.status == "ACTIVE":
            for product_id, quantity in reservation.items.items():
                stock = self.stock[product_id]
                stock.reserved -= quantity
            reservation.status = "RELEASED"

        # Successful no-ops also claim their request IDs.
        return self._record_request(request_id, "RELEASE", reservation_id, reservation)

    def get_reservation(self, reservation_id: int) -> Reservation:
        reservation = self.reservations.get(reservation_id)
        if reservation is None:
            raise Exception("Reservation doesn't exist")
        return deepcopy(reservation)

    @staticmethod
    def _validate_id(value: str, name: str) -> None:
        if not isinstance(value, str) or not value:
            raise Exception(f"{name} must be a nonempty string")

    @staticmethod
    def _validate_quantity(quantity: int) -> None:
        # bool is an int subclass, so reject it explicitly.
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
            raise Exception(f"Quantity must be positive: {quantity}")

    def _validate_items(self, items: dict[ProductID, int]) -> dict[ProductID, int]:
        """Validate the entire cart before any stock is changed."""
        if not items:
            raise Exception("Empty items")
        validated_items = {}
        for product_id, quantity in items.items():
            if product_id not in self.stock:
                raise Exception(f"Invalid product_id: {product_id}")
            self._validate_quantity(quantity)
            if quantity > self.stock[product_id].available:
                raise Exception(f"Quantity not available: {product_id}:{quantity}")
            validated_items[product_id] = quantity

        return validated_items

    def _replay_request(
        self, request_id: str, operation: RequestType, payload: Hashable
    ) -> Reservation | None:
        request = self.requests.get(request_id)
        if request is None:
            return None
        if request.type_ != operation:
            raise Exception(
                "Idempotency conflict: existing request_id is not a "
                f"`{operation.lower()}` operation"
            )
        if request.payload != payload:
            raise Exception(
                "Idempotency conflict: request_id was used with a different payload"
            )
        return deepcopy(request.result)

    def _record_request(
        self,
        request_id: str,
        operation: RequestType,
        payload: Hashable,
        result: Reservation,
    ) -> Reservation:
        """Keep live state, cached responses, and caller snapshots independent."""
        self.requests[request_id] = Request(
            id_=request_id,
            type_=operation,
            payload=payload,
            result=deepcopy(result),
        )
        return deepcopy(result)
