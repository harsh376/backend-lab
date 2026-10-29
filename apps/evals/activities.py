"""Dataset loading, answer execution, and retrieval scoring for the eval worker."""

import asyncio
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from temporalio import activity
from temporalio.client import Client, WorkflowFailureError
from temporalio.exceptions import ApplicationError

from apps.evals.datasets.dataset import load_cases, select_cases
from apps.evals.datasets.hosted_dataset import HostedDatasetService
from apps.evals.evaluators.answers import evaluate_correctness
from apps.evals.evaluators.retrieval import RETRIEVAL_METRICS, evaluate_retrieval
from apps.evals.experiments import (
    case_trace_context,
    experiment_item,
)
from apps.evals.models import EvalCase
from apps.evals.workflow import EvalCaseRequest, EvalRunRequest
from apps.mcp import telemetry
from apps.mcp.agent.models import AnswerRequest
from apps.mcp.agent.workflow import AnswerWorkflow
from apps.mcp.telemetry import current_context, observation, observe
from backend.config import Settings
from backend.services.kilt.kilt import KiltService


async def _evaluate_answer_correctness(case: EvalCase, output: dict) -> dict:
    if output["status"] != "COMPLETED":
        return {"reason": "Answer run did not complete."}
    answer = output["result"]
    return await evaluate_correctness(
        case, answer["short_answer"], abstained=answer.get("abstained", False)
    )


EVALUATORS = [
    ("answer_correctness", _evaluate_answer_correctness),
]


@activity.defn(name="load_eval_cases")
@observe(
    input=lambda args: {
        "case_id": args["request"].case_id,
        "limit": args["request"].limit,
        "tags": args["request"].tags,
        **(
            {"hosted_dataset": args["request"].hosted_dataset}
            if args["request"].hosted_dataset is not None
            else {}
        ),
    },
    output=lambda cases: {"count": len(cases), "case_ids": [c.case_id for c in cases]},
    session_id=lambda args: activity.info().workflow_id,
    metadata=lambda args: {
        "eval_run_id": activity.info().workflow_id,
        "answer_id": None,
    },
)
async def load_eval_cases(request: EvalRunRequest) -> list[EvalCase]:
    try:
        request.validate()
        cases = (
            await HostedDatasetService().read(request.hosted_dataset)
            if request.hosted_dataset is not None
            else load_cases(Path(__file__).parent / "datasets/kilt-v1/dev.json")
        )
        return select_cases(
            cases=cases,
            case_id=request.case_id,
            limit=request.limit,
            tags=request.tags,
        )
    except (OSError, ValueError) as error:
        raise ApplicationError(str(error), non_retryable=True) from error


@activity.defn(name="evaluate_mcp_case")
@observe(
    "eval_case",
    trace_context=case_trace_context,
    input=lambda args: args["request"].case.model_dump(mode="json"),
    session_id=lambda args: activity.info().workflow_id,
    metadata=lambda args: {
        "eval_run_id": activity.info().workflow_id,
        "answer_id": None,
        "case_id": args["request"].case.case_id,
        "tags": args["request"].case.tags,
    },
)
async def evaluate_mcp_case(request: EvalCaseRequest) -> dict:
    case = request.case
    context = current_context()
    with experiment_item(request) as report:
        result = await _generate_answer(
            case, request.timeout, context, request.timeout_settings
        )
        result["evaluators"] = await _run_evaluators(case, result["output"])
        if context:
            result["trace_id"] = context["trace_id"]
        result.update(report)
        _record_evaluation(result)
        return result


async def _run_evaluators(case: EvalCase, output: dict) -> dict:
    judgments = {}
    for evaluator_name, evaluator in EVALUATORS:
        judgments[evaluator_name] = await _evaluate_one(
            case, output, evaluator_name, evaluator
        )
    return judgments


@observe(
    name=lambda args: args["evaluator_name"],
    input=lambda args: {
        "case": args["case"].model_dump(mode="json"),
        "output": args["output"],
    },
    trace_context=lambda args: None,
    session_id=lambda args: activity.info().workflow_id,
    metadata=lambda args: {"case_id": args["case"].case_id},
)
async def _evaluate_one(case, output, evaluator_name, evaluator):
    judgment = await evaluator(case, output)
    if judgment.get("error"):
        _mark_evaluator_error("Evaluator failed")
    return judgment


def _mark_evaluator_error(message):
    instance = telemetry.client()
    if instance is not None:
        instance.update_current_span(level="ERROR", status_message=message)


def _record_evaluation(result):
    instance = telemetry.client()
    if instance is None:
        return
    instance.update_current_span(
        metadata={
            "answer_id": result["output"].get("run_id"),
            "answer_trace_id": result.get("answer_trace_id"),
        }
    )
    for name, judgment in result["evaluators"].items():
        for metric, value in judgment.items():
            if (metric == "correctness" or metric in RETRIEVAL_METRICS) and isinstance(
                value, (int, float)
            ):
                instance.score_current_span(
                    name=metric,
                    value=value,
                    data_type="NUMERIC",
                    comment=judgment.get("reason"),
                )
        if judgment.get("error"):
            _mark_evaluator_error(f"{name} evaluator failed")
    if result["output"]["status"] != "COMPLETED":
        _mark_evaluator_error(result["output"]["status"])


async def _generate_answer(case, timeout, eval_context, timeout_settings=None):
    """Run the answer directly; stable IDs prevent duplicate submissions."""
    info = activity.info()
    run_id = (
        "kilt-answer-eval-"
        + uuid5(
            NAMESPACE_URL,
            f"{info.workflow_id}/{info.workflow_run_id}/{info.activity_id}",
        ).hex
    )
    trace_id = (eval_context or {}).get("trace_id") or uuid5(NAMESPACE_URL, run_id).hex
    started = asyncio.get_running_loop().time()
    output = {"run_id": run_id, "status": "TIMEOUT"}
    # Keep answer generations in the experiment trace for native cost aggregation.
    with observation(
        "answer",
        input=case.question,
        trace_context=eval_context or {"trace_id": trace_id},
        session_id=info.workflow_id,
        metadata={
            "answer_id": run_id,
            "eval_run_id": info.workflow_id,
            "eval_trace_id": (eval_context or {}).get("trace_id"),
            "case_id": case.case_id,
        },
    ) as span:
        try:
            async with asyncio.timeout(timeout):
                client = await Client.connect(Settings().temporal_address)
                handle = await client.start_workflow(
                    AnswerWorkflow.run,
                    AnswerRequest(
                        case.question,
                        limit=10,
                        timeout_settings=timeout_settings,
                        trace_context=current_context(),
                        session_id=info.workflow_id,
                    ),
                    id=run_id,
                    task_queue="kilt-answers",
                    execution_timeout=timedelta(seconds=timeout),
                )
                answer = await handle.result()
                output.update(status="COMPLETED", result=asdict(answer))
        except TimeoutError:
            pass
        except WorkflowFailureError as error:
            output.update(status="FAILED", error=str(error.cause))
        if span is not None:
            span.update(output=output)
    return {
        "case_id": case.case_id,
        "output": output,
        "answer_trace_id": trace_id if eval_context else None,
        "elapsed_seconds": asyncio.get_running_loop().time() - started,
        "evaluators": {},
    }


class RetrievalEvalActivities:
    def __init__(self, kilt_service: KiltService):
        self.kilt_service = kilt_service

    @activity.defn(name="evaluate_retrieval_case")
    @observe(
        "retrieval_eval_case",
        trace_context=case_trace_context,
        input=lambda args: args["request"].case.model_dump(mode="json"),
        session_id=lambda args: activity.info().workflow_id,
        metadata=lambda args: {
            "eval_run_id": activity.info().workflow_id,
            "case_id": args["request"].case.case_id,
            "eval_type": "retrieval",
            "retrieval_limit": args["request"].retrieval_limit,
        },
    )
    async def evaluate(self, request: EvalCaseRequest) -> dict:
        case = request.case
        context = current_context()
        with experiment_item(request) as report:
            started = asyncio.get_running_loop().time()
            async with asyncio.timeout(request.timeout):
                evidences = await self.kilt_service.asearch_evidences(
                    case.question, request.retrieval_limit
                )
            elapsed = asyncio.get_running_loop().time() - started
            candidates = {
                "ranked_page_ids": [e.wikipedia_id for e in evidences],
                "ranked_paragraph_counts": [len(e.paragraphs) for e in evidences],
                "limit": request.retrieval_limit,
                "corpus_version": self.kilt_service.corpus_version,
            }
            result = {
                "case_id": case.case_id,
                "output": {"status": "COMPLETED", "result": candidates},
                "evaluators": {
                    "retrieval_recall_at_k": evaluate_retrieval(case, candidates)
                },
                "elapsed_seconds": elapsed,
                **report,
            }
            if context:
                result["trace_id"] = context["trace_id"]
            _record_evaluation(result)
            return result
