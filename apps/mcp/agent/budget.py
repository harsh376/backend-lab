"""Deterministic workflow budget scopes backed by recorded activity results."""

from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from apps.mcp.agent.models import SynthesisInput, VerificationInput
    from backend.budget import BudgetReport, Reservation


class BudgetStopped(Exception):
    """The workflow must abstain instead of dispatching more model calls."""


@dataclass
class BudgetStage:
    usage_cost_usd: float | None = None

    def record_cost(self, usage_cost_usd: float | None) -> None:
        self.usage_cost_usd = usage_cost_usd


@asynccontextmanager
async def budget_stage(
    budget_report: BudgetReport | None,
    stage: str,
    data: SynthesisInput | VerificationInput,
):
    if budget_report is None:
        yield BudgetStage()
        return
    try:
        quote = await workflow.execute_activity(
            f"quote_{stage}",
            data,
            result_type=Reservation,
            start_to_close_timeout=timedelta(seconds=30),
            schedule_to_close_timeout=timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
    except ActivityError as error:
        budget_report.stop_reason = "reservation_unavailable"
        raise BudgetStopped from error
    if not budget_report.reserve(stage, quote):
        raise BudgetStopped
    # The quote is recorded before the model activity is scheduled.
    data.reservation = quote
    accounting = BudgetStage()
    try:
        yield accounting
        if not budget_report.reconcile(accounting.usage_cost_usd):
            raise BudgetStopped
    except ActivityError as error:
        budget_report.entries[-1].status = "unresolved"
        budget_report.stop_reason = "unknown_provider_outcome"
        raise BudgetStopped from error
