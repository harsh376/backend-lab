import json
from dataclasses import asdict
from hashlib import sha256
from uuid import uuid4

from mcp.server import MCPServer
from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from apps.mcp.agent.models import AnswerRequest, AnswerResult
from apps.mcp.agent.workflow import AnswerWorkflow
from apps.mcp.telemetry import (
    chat_session,
    current_context,
    current_session_id,
    observe,
    update_metadata,
)
from apps.mcp.telemetry import client as telemetry_client
from backend.config import Settings

mcp = MCPServer("Evidence-backed answers", middleware=[chat_session])


async def temporal_client() -> Client:
    return await Client.connect(Settings().temporal_address)


@mcp.tool()
@observe(
    reuse_current=True,
    as_type="tool",
    input=lambda args: args["question"],
    output=lambda result: result["run_id"],
)
async def answer(
    question: str,
    limit: int = 5,
    budget_usd: float | None = None,
    idempotency_key: str | None = None,
) -> dict:
    """Start an answer run, optionally limiting model spend with budget_usd.

    Poll get_answer for its result and per-call budget reservations.
    Retry with the same idempotency_key and arguments to reuse a run. Keys are
    shared within the Temporal namespace and expire with workflow retention.
    """
    request = AnswerRequest(question, limit, budget_usd=budget_usd)
    request.validate()
    run_id = f"kilt-answer-{uuid4()}"
    start_options = {}
    fingerprint = None
    if idempotency_key is not None:
        run_id, fingerprint, start_options = _idempotent_start_options(
            idempotency_key, request
        )
    update_metadata({"answer_id": run_id})
    request.trace_context = current_context()
    request.session_id = current_session_id()
    client = await temporal_client()
    try:
        await client.start_workflow(
            AnswerWorkflow.run,
            request,
            id=run_id,
            task_queue="kilt-answers",
            **start_options,
        )
    except WorkflowAlreadyStartedError:
        if fingerprint is None:
            raise
        return await _existing_answer(client, run_id, fingerprint)
    return {"run_id": run_id, "status": "RUNNING"}


def _idempotent_start_options(
    key: str, request: AnswerRequest
) -> tuple[str, str, dict]:
    """Validate the key and prepare a stable workflow ID and duplicate policies."""
    if not key.strip() or len(key) > 256:
        raise ValueError("idempotency_key must contain 1 to 256 characters")
    key_hash = sha256(key.encode()).hexdigest()
    run_id = f"kilt-answer-idem-{key_hash}"
    fingerprint = _request_fingerprint(request)
    start_options = {
        "id_reuse_policy": WorkflowIDReusePolicy.REJECT_DUPLICATE,
        "id_conflict_policy": WorkflowIDConflictPolicy.FAIL,
        "memo": {"answer_request_sha256": fingerprint},
    }
    return run_id, fingerprint, start_options


def _request_fingerprint(request: AnswerRequest) -> str:
    """Hash answer arguments, excluding per-submission tracing context."""
    payload = {
        "question": request.question,
        "limit": request.limit,
        "budget_usd": request.budget_usd,
    }
    return sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


async def _existing_answer(client: Client, run_id: str, fingerprint: str) -> dict:
    """Return an existing run only when its original arguments match."""
    description = await client.get_workflow_handle(run_id).describe()
    memo = await description.memo()
    if memo.get("answer_request_sha256") != fingerprint:
        raise ValueError(
            "idempotency_key was already used with different arguments"
        ) from None
    return {"run_id": run_id, "status": description.status.name}


@mcp.tool()
@observe(
    reuse_current=True,
    as_type="tool",
    metadata=lambda args: {"answer_id": args["run_id"]},
    input=lambda args: args["run_id"],
    output=lambda result: (
        "\n\n".join(
            text
            for text in (
                result["result"]["short_answer"],
                result["result"]["explanation"],
            )
            if text
        )
        if "result" in result
        else result["status"]
    ),
)
async def get_answer(run_id: str) -> dict:
    """Return run status and, on completion, answer text and original citations."""
    if not run_id.startswith("kilt-answer-"):
        raise ValueError("invalid answer run ID")
    return await _get_answer(run_id)


async def _get_answer(run_id: str) -> dict:
    client = await temporal_client()
    handle = client.get_workflow_handle(run_id, result_type=AnswerResult)
    description = await handle.describe()
    result = {"run_id": run_id, "status": description.status.name}
    if description.status == WorkflowExecutionStatus.COMPLETED:
        answer_result = await handle.result()
        result["result"] = asdict(answer_result)
        if answer_result.budget is not None:
            result["result"]["budget"]["overrun_usd"] = answer_result.budget.overrun_usd
    return result


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="MCP entrypoint for AnswerWorkflow")
    parser.add_argument(
        "--transport", choices=("stdio", "streamable-http"), default="stdio"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()
    # Install the tracer provider before the SDK opens its first request span.
    telemetry_client()
    if args.transport == "stdio":
        mcp.run()
    else:
        mcp.run(transport="streamable-http", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
