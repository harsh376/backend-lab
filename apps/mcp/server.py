from dataclasses import asdict
from uuid import uuid4

from mcp.server import MCPServer
from temporalio.client import Client, WorkflowExecutionStatus

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
async def answer(question: str, limit: int = 5) -> dict:
    """Start a durable evidence-verified answer run; poll get_answer for its result."""
    request = AnswerRequest(question, limit)
    request.validate()
    run_id = f"kilt-answer-{uuid4()}"
    update_metadata({"answer_id": run_id})
    request.trace_context = current_context()
    request.session_id = current_session_id()
    client = await temporal_client()
    await client.start_workflow(
        AnswerWorkflow.run, request, id=run_id, task_queue="kilt-answers"
    )
    return {"run_id": run_id, "status": "RUNNING"}


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
        result["result"] = asdict(await handle.result())
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
