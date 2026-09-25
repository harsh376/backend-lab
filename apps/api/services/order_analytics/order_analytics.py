"""Service-level debugging exercise.

Contract:
- Timestamps are integer UTC epoch seconds; ranges are [start, end).
- Only completed orders contribute to reports.
- Revenue is gross_cents minus refunded_cents.
- Summary metrics cover all matching orders, independent of pagination.
- Orders sort by (created_at, order_id), ascending.
- Average order value is net revenue / order count, rounded to two decimal
  places using Decimal ROUND_HALF_UP, expressed in cents.
- Empty reports return zero metrics and an empty orders tuple.
- A zero limit or offset beyond the results returns an empty page while
  preserving summary metrics.
- Invalid inputs raise ValueError without changing stored orders.



Reported broken behavior:
- Adjacent time-range reports sometimes count the same order twice.
- Reports containing cancelled orders show incorrect totals.
- Changing pagination changes summary metrics.
- Requests with no matching orders—or an empty result page—raise an exception
instead of returning a report.
The service imports successfully, and I verified these symptoms. No fixes
or solution hints included.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

type OrderStatus = Literal["pending", "completed", "cancelled"]


@dataclass(frozen=True)
class Order:
    order_id: str
    customer_id: str
    created_at: int
    status: OrderStatus
    gross_cents: int
    refunded_cents: int = 0


@dataclass(frozen=True)
class AnalyticsReport:
    order_count: int
    revenue_cents: int
    average_order_value_cents: Decimal
    orders: tuple[Order, ...]


class OrderAnalyticsService:
    def __init__(self) -> None:
        self._orders: dict[str, Order] = {}

    def add_order(self, order: Order) -> None:
        if not isinstance(order.order_id, str) or not order.order_id.strip():
            raise ValueError("order_id must be a nonempty string")
        if not isinstance(order.customer_id, str) or not order.customer_id.strip():
            raise ValueError("customer_id must be a nonempty string")
        if order.order_id in self._orders:
            raise ValueError("order_id already exists")
        if type(order.created_at) is not int:
            raise ValueError("created_at must be an integer")
        if order.status not in ("pending", "completed", "cancelled"):
            raise ValueError("invalid status")
        if type(order.gross_cents) is not int or order.gross_cents < 0:
            raise ValueError("gross_cents must be a nonnegative integer")
        if (
            type(order.refunded_cents) is not int
            or not 0 <= order.refunded_cents <= order.gross_cents
        ):
            raise ValueError("refunded_cents must be between zero and gross_cents")
        self._orders[order.order_id] = order

    def report(
        self,
        start: int,
        end: int,
        customer_id: str | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> AnalyticsReport:
        if type(start) is not int or type(end) is not int or start >= end:
            raise ValueError("start and end must be integers with start < end")
        if type(offset) is not int or offset < 0:
            raise ValueError("offset must be a nonnegative integer")
        if type(limit) is not int or limit < 0:
            raise ValueError("limit must be a nonnegative integer")
        if customer_id is not None and (
            not isinstance(customer_id, str) or not customer_id.strip()
        ):
            raise ValueError("customer_id must be a nonempty string or None")

        matching = [
            order
            for order in self._orders.values()
            if start <= order.created_at < end
            and order.status == "completed"
            and (customer_id is None or order.customer_id == customer_id)
        ]
        matching.sort(key=lambda order: (order.created_at, order.order_id))
        revenue = sum(order.gross_cents - order.refunded_cents for order in matching)
        average = Decimal(0)
        if matching:
            average = (Decimal(revenue) / Decimal(len(matching))).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        page = matching[offset : offset + limit]
        return AnalyticsReport(
            order_count=len(matching),
            revenue_cents=revenue,
            average_order_value_cents=average,
            orders=tuple(page),
        )
