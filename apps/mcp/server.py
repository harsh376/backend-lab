from dataclasses import asdict
from uuid import uuid4

from mcp.server import MCPServer
from temporalio.client import Client, WorkflowExecutionStatus

from apps.mcp.agent.models import AnswerRequest, AnswerResult
from apps.mcp.agent.workflow import AnswerWorkflow
from apps.mcp.config import Settings

mcp = MCPServer("Evidence-backed answers")


async def temporal_client() -> Client:
    return await Client.connect(Settings().temporal_address)


@mcp.tool()
async def answer(question: str, limit: int = 5) -> dict:
    """Start a durable extractive answer run; poll get_answer for its result."""
    request = AnswerRequest(question, limit)
    request.validate()
    client = await temporal_client()
    run_id = f"kilt-answer-{uuid4()}"
    await client.start_workflow(
        AnswerWorkflow.run, request, id=run_id, task_queue="kilt-answers"
    )
    return {"run_id": run_id, "status": "RUNNING"}


@mcp.tool()
async def get_answer(run_id: str) -> dict:
    """Return run status and, on completion, answer text and original citations."""
    if not run_id.startswith("kilt-answer-"):
        raise ValueError("invalid answer run ID")
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
