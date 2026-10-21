"""Durable eval orchestration; answer execution and scoring run in activities."""

from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from apps.evals.models import EvalCase

TASK_QUEUE = "kilt-evals"


@dataclass
class EvalRunRequest:
    cases: list[EvalCase]
    timeout: float = 120
    trace_context: dict[str, str] | None = None


@workflow.defn
class EvalWorkflow:
    @workflow.run
    async def run(self, request: EvalRunRequest) -> list[dict]:
        results = []
        for case in request.cases:
            try:
                result = await workflow.execute_activity(
                    "evaluate_mcp_case",
                    EvalRunRequest(
                        cases=[case],
                        timeout=request.timeout,
                        trace_context=request.trace_context,
                    ),
                    result_type=dict,
                    start_to_close_timeout=timedelta(seconds=request.timeout + 90),
                    # Repeating this activity could submit another answer run.
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )
            except ActivityError as error:
                result = {
                    "case_id": case.case_id,
                    "output": {"status": "FAILED", "error": str(error.cause)},
                    "evaluators": {},
                }
            results.append(result)
        return results
