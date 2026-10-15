from dataclasses import asdict
from uuid import uuid4

from mcp.server import MCPServer
from temporalio.client import Client, WorkflowExecutionStatus

from apps.mcp.agent.models import AnswerRequest, AnswerResult
from apps.mcp.agent.workflow import AnswerWorkflow
from apps.mcp.telemetry import current_context, observation
from backend.config import Settings

mcp = MCPServer("Evidence-backed answers")


async def temporal_client() -> Client:
    return await Client.connect(Settings().temporal_address)


@mcp.tool()
async def answer(question: str, limit: int = 5) -> dict:
    """Start a durable extractive answer run; poll get_answer for its result."""
    request = AnswerRequest(question, limit)
    request.validate()
    run_id = f"kilt-answer-{uuid4()}"
    with observation(
        "mcp.answer",
        input={"question": question, "limit": limit},
        metadata={"answer_id": run_id},
    ) as span:
        request.trace_context = current_context()
        client = await temporal_client()
        await client.start_workflow(
            AnswerWorkflow.run, request, id=run_id, task_queue="kilt-answers"
        )
        if span:
            span.update(output={"run_id": run_id, "status": "RUNNING"})
    return {"run_id": run_id, "status": "RUNNING"}


@mcp.tool()
async def get_answer(run_id: str) -> dict:
    """Return run status and, on completion, answer text and original citations."""
    if not run_id.startswith("kilt-answer-"):
        raise ValueError("invalid answer run ID")
    with observation(
        "mcp.get_answer",
        input={"run_id": run_id},
        metadata={"answer_id": run_id},
    ) as span:
        result = await _get_answer(run_id)
        if span:
            span.update(output={"status": result["status"]})
        return result


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
    if args.transport == "stdio":
        mcp.run()
    else:
        mcp.run(transport="streamable-http", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
