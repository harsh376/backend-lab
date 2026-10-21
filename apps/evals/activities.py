"""Direct AnswerWorkflow execution and scoring for the eval worker."""

import asyncio
from dataclasses import asdict
from datetime import timedelta
from uuid import NAMESPACE_URL, uuid5

from opentelemetry.trace import INVALID_SPAN, use_span
from temporalio import activity
from temporalio.client import Client, WorkflowFailureError

from apps.evals.evaluators.answers import evaluate_correctness
from apps.evals.workflow import EvalRunRequest
from apps.mcp.agent.models import AnswerRequest
from apps.mcp.agent.workflow import AnswerWorkflow
from apps.mcp.telemetry import current_context, observation
from backend.config import Settings

EVALUATORS = [("answer_correctness", evaluate_correctness)]


@activity.defn(name="evaluate_mcp_case")
async def evaluate_mcp_case(request: EvalRunRequest) -> dict:
    case = request.cases[0]
    info = activity.info()
    with observation(
        "eval",
        trace_context=request.trace_context,
        input={"question": case.question, "accepted_answers": case.accepted_answers},
        session_id=info.workflow_id,
        metadata={
            "eval_run_id": info.workflow_id,
            "temporal_run_id": info.workflow_run_id,
            "activity_id": info.activity_id,
            "attempt": info.attempt,
            "case_id": case.case_id,
            "tags": case.tags,
        },
    ) as span:
        context = current_context()
        result = await evaluate_answer_case(case, request.timeout, context)
        for evaluator_name, evaluator in EVALUATORS:
            judgment = {"reason": "Answer run did not complete."}
            if result["output"]["status"] == "COMPLETED":
                answer = result["output"]["result"]
                with observation(
                    evaluator_name,
                    input={
                        "question": case.question,
                        "accepted_answers": case.accepted_answers,
                        "actual_answer": answer["short_answer"],
                    },
                    metadata={"case_id": case.case_id},
                ) as evaluator_span:
                    judgment = await evaluator(
                        case,
                        answer["short_answer"],
                        abstained=answer.get("abstained", False),
                    )
                    if evaluator_span is not None:
                        evaluator_span.update(output=judgment)
                        if judgment.get("error"):
                            evaluator_span.update(
                                level="ERROR", status_message="Evaluator failed"
                            )
            result["evaluators"][evaluator_name] = judgment
            if span is not None:
                for metric, value in judgment.items():
                    if isinstance(value, (int, float)):
                        span.score(
                            name=metric,
                            value=value,
                            data_type="NUMERIC",
                            comment=judgment.get("reason"),
                        )
                if judgment.get("error"):
                    span.update(
                        level="ERROR",
                        status_message=f"{evaluator_name} evaluator failed",
                    )
        if span is not None:
            if context:
                result["trace_id"] = context["trace_id"]
            span.update(
                output=result,
                metadata={
                    "answer_id": result["output"].get("run_id"),
                    "answer_trace_id": result.get("answer_trace_id"),
                },
            )
            if result["output"]["status"] != "COMPLETED":
                span.update(level="ERROR", status_message=result["output"]["status"])
        return result


async def evaluate_answer_case(case, timeout, eval_context):
    """Run the answer directly; stable IDs prevent duplicate submissions."""
    info = activity.info()
    run_id = (
        "kilt-answer-eval-"
        + uuid5(
            NAMESPACE_URL,
            f"{info.workflow_id}/{info.workflow_run_id}/{info.activity_id}",
        ).hex
    )
    trace_id = uuid5(NAMESPACE_URL, run_id).hex
    started = asyncio.get_running_loop().time()
    output = {"run_id": run_id, "status": "TIMEOUT"}
    # Detach the answer root so its model cost and latency are independent.
    with (
        use_span(INVALID_SPAN),
        observation(
            "answer",
            input=case.question,
            trace_context={"trace_id": trace_id},
            session_id=info.workflow_id,
            metadata={
                "answer_id": run_id,
                "eval_run_id": info.workflow_id,
                "eval_trace_id": (eval_context or {}).get("trace_id"),
                "case_id": case.case_id,
            },
        ) as span,
    ):
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
