"""Durable eval orchestration; answer execution and scoring run in activities."""

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Literal

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError

with workflow.unsafe.imports_passed_through():
    from apps.evals.models import EvalCase

TASK_QUEUE = "kilt-evals"


@dataclass
class EvalRunRequest:
    case_id: str | None = None
    limit: int | None = 3
    tags: list[str] = field(default_factory=lambda: ["page_verified"])
    timeout: float = 120
    trace_context: dict[str, str] | None = None
    experiment_name: str | None = None
    hosted_dataset: str | None = None
    eval_type: Literal["answer", "retrieval"] = "answer"
    retrieval_limit: int = 100

    def validate(self) -> None:
        if self.eval_type not in {"answer", "retrieval"}:
            raise ValueError("eval_type must be answer or retrieval")
        if not 1 <= self.retrieval_limit <= 100:
            raise ValueError("retrieval_limit must be between 1 and 100")
        if not 0 < self.timeout <= 3600:
            raise ValueError("timeout must be between 0 and 3600 seconds")
        if self.experiment_name is not None and not self.experiment_name.strip():
            raise ValueError("experiment_name must not be blank")
        if self.hosted_dataset is not None and not self.hosted_dataset.strip():
            raise ValueError("hosted_dataset must not be blank")
        if self.limit is not None and self.limit <= 0:
            raise ValueError("limit must be positive")


@dataclass
class EvalCaseRequest:
    case: EvalCase
    timeout: float = 120
    trace_context: dict[str, str] | None = None
    experiment_name: str | None = None
    eval_type: Literal["answer", "retrieval"] = "answer"
    retrieval_limit: int = 100


@workflow.defn
class EvalWorkflow:
    @workflow.run
    async def run(self, request: EvalRunRequest) -> list[dict]:
        try:
            request.validate()
        except ValueError as error:
            raise ApplicationError(str(error), non_retryable=True) from error
        cases = await workflow.execute_activity(
            "load_eval_cases",
            request,
            result_type=list[EvalCase],
            start_to_close_timeout=timedelta(
                seconds=120 if request.hosted_dataset is not None else 30
            ),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
        results = []
        for case in cases:
            try:
                result = await workflow.execute_activity(
                    "evaluate_retrieval_case"
                    if request.eval_type == "retrieval"
                    else "evaluate_mcp_case",
                    EvalCaseRequest(
                        case=case,
                        timeout=request.timeout,
                        trace_context=request.trace_context,
                        experiment_name=request.experiment_name,
                        eval_type=request.eval_type,
                        retrieval_limit=request.retrieval_limit,
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
            result["case"] = case.model_dump(mode="json")
            results.append(result)
        return results
