"""Per-run model spend reservations; independent of trace aggregation."""

import math
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Literal


@dataclass
class Reservation:
    model: str
    max_tokens: int
    reserved_cost_usd: float


current_reservation: ContextVar[Reservation | None] = ContextVar(
    "model_reservation", default=None
)


@dataclass
class BudgetEntry:
    stage: str
    reservation: Reservation
    usage_cost_usd: float | None = None
    status: Literal["reserved", "reconciled", "reservation_overrun", "unresolved"] = (
        "reserved"
    )

    @property
    def committed_usd(self) -> float:
        if self.usage_cost_usd is not None:
            return self.usage_cost_usd
        return self.reservation.reserved_cost_usd


@dataclass
class BudgetReport:
    limit_usd: float
    entries: list[BudgetEntry] = field(default_factory=list)
    stop_reason: str | None = None

    @property
    def committed_usd(self) -> float:
        return sum(entry.committed_usd for entry in self.entries)

    @property
    def overrun_usd(self) -> float:
        return max(0.0, self.committed_usd - self.limit_usd)

    def reserve(self, stage: str, quote: Reservation) -> bool:
        if (
            not math.isfinite(quote.reserved_cost_usd)
            or quote.reserved_cost_usd < 0
            or self.committed_usd + quote.reserved_cost_usd > self.limit_usd
        ):
            self.stop_reason = "insufficient_budget"
            return False
        self.entries.append(BudgetEntry(stage, quote))
        return True

    def reconcile(self, cost: float | None) -> bool:
        entry = self.entries[-1]
        if cost is None or not math.isfinite(cost) or cost < 0:
            entry.status = "unresolved"
            self.stop_reason = "unknown_cost"
            return False
        entry.usage_cost_usd = cost
        entry.status = (
            "reservation_overrun"
            if cost > entry.reservation.reserved_cost_usd
            else "reconciled"
        )
        return True
