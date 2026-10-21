"""Direct AnswerWorkflow execution and scoring for the eval worker."""

import asyncio
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from temporalio import activity
from temporalio.client import Client, WorkflowFailureError
from temporalio.exceptions import ApplicationError

from apps.evals.dataset import load_cases, select_cases
from apps.evals.evaluators.answers import evaluate_correctness
from apps.evals.evaluators.retrieval import evaluate_mapk, evaluate_mrrk
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

EVALUATORS = [
    ("answer_correctness", evaluate_correctness, "answer"),
    ("retrieval_mapk", evaluate_mapk, "retrieval"),
    ("retrieval_mrrk", evaluate_mrrk, "retrieval"),
]


@activity.defn(name="load_eval_cases")
@observe(
    input=lambda args: {
        "case_id": args["request"].case_id,
        "limit": args["request"].limit,
        "tags": args["request"].tags,
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
        return select_cases(
            cases=load_cases(Path(__file__).parent / "datasets/kilt-v1/dev.json"),
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
    input=lambda args: {
        "question": args["request"].case.question,
        "accepted_answers": args["request"].case.accepted_answers,
        "accepted_pages": sorted(
            {
                evidence.wikipedia_id
                for evidence_set in args["request"].case.evidence_sets
                for evidence in evidence_set
            }
        ),
    },
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
        result = await _generate_answer(case, request.timeout, context)
        await _run_evaluators(case, result, request.retrieval_k)
        if context:
            result["trace_id"] = context["trace_id"]
        result.update(report)
        _record_evaluation(result)
        return result


async def _run_evaluators(case, result, k):
    for evaluator_name, evaluator, kind in EVALUATORS:
        judgment = {"reason": "Answer run did not complete."}
        if result["output"]["status"] == "COMPLETED":
            judgment = await _evaluate_one(
                case, result["output"]["result"], evaluator_name, evaluator, kind, k
            )
        result["evaluators"][evaluator_name] = judgment


def _evaluator_input(args):
    case, answer = args["case"], args["answer"]
    if args["kind"] == "retrieval":
        return {
            "retrieved_passages": answer.get("retrieved_passages"),
            "evidence_sets": [
                [e.model_dump() for e in group] for group in case.evidence_sets
            ],
            "k": args["k"],
        }
    return {
        "question": case.question,
        "accepted_answers": case.accepted_answers,
        "actual_answer": answer["short_answer"],
    }


@observe(
    name=lambda args: args["evaluator_name"],
    input=_evaluator_input,
    trace_context=lambda args: None,
    session_id=lambda args: activity.info().workflow_id,
    metadata=lambda args: {"case_id": args["case"].case_id},
)
async def _evaluate_one(case, answer, evaluator_name, evaluator, kind, k):
    if kind == "retrieval":
        judgment = await evaluator(case, answer.get("retrieved_passages"), k=k)
    else:
        judgment = await evaluator(
            case, answer["short_answer"], abstained=answer.get("abstained", False)
        )
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
            if metric in {
                "correctness",
                "ap_at_k",
                "reciprocal_rank_at_k",
            } and isinstance(value, (int, float)):
                instance.score_current_span(
                    name=(
                        f"{metric.removesuffix('_at_k')}_at_{judgment['k']}"
                        if "k" in judgment
                        else metric
                    ),
                    value=value,
                    data_type="NUMERIC",
                    comment=judgment.get("reason"),
                )
        if judgment.get("error"):
            _mark_evaluator_error(f"{name} evaluator failed")
    if result["output"]["status"] != "COMPLETED":
        _mark_evaluator_error(result["output"]["status"])


async def _generate_answer(case, timeout, eval_context):
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
