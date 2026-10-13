import json
from unittest.mock import AsyncMock, Mock

import anyio
from mcp import ClientSession
from mcp.shared.memory import create_client_server_memory_streams
from temporalio.client import WorkflowExecutionStatus

from apps.mcp import server
from apps.mcp.agent.models import AnswerRequest, AnswerResult, Passage
from apps.mcp.agent.workflow import AnswerWorkflow


async def test_mcp_answer_protocol(monkeypatch):
    passage = Passage("v:1:0", "v", "1", 0, "Title", "Evidence")
    handle = Mock()
    handle.describe = AsyncMock(
        return_value=Mock(status=WorkflowExecutionStatus.RUNNING)
    )
    handle.result = AsyncMock(return_value=AnswerResult("Evidence", "quote", [passage]))
    client = Mock()
    client.start_workflow = AsyncMock()
    client.get_workflow_handle.return_value = handle
    connect = AsyncMock(return_value=client)
    monkeypatch.setattr(server, "temporal_client", connect)

    async with (
        create_client_server_memory_streams() as (
            client_streams,
            server_streams,
        ),
        anyio.create_task_group() as tasks,
    ):
        lowlevel = server.mcp._lowlevel_server
        tasks.start_soon(
            lowlevel.run,
            *server_streams,
            lowlevel.create_initialization_options(),
        )
        async with ClientSession(*client_streams) as session:
            await session.initialize()
            tools = await session.list_tools()
            assert {tool.name for tool in tools.tools} == {"answer", "get_answer"}

            invalid = await session.call_tool("answer", {"question": " "})
            assert invalid.is_error
            connect.assert_not_awaited()

            started = await session.call_tool("answer", {"question": "question"})
            assert not started.is_error
            run = json.loads(started.content[0].text)
            client.start_workflow.assert_awaited_once_with(
                AnswerWorkflow.run,
                AnswerRequest("question", 5),
                id=run["run_id"],
                task_queue="kilt-answers",
            )
            pending = await session.call_tool("get_answer", {"run_id": run["run_id"]})
            assert json.loads(pending.content[0].text)["status"] == "RUNNING"
            handle.result.assert_not_awaited()

            handle.describe.return_value.status = WorkflowExecutionStatus.COMPLETED
            completed = await session.call_tool("get_answer", {"run_id": run["run_id"]})
            result = json.loads(completed.content[0].text)["result"]
            assert result["short_answer"] == "Evidence"
            assert result["citations"][0]["passage_id"] == passage.passage_id

            handle.describe.return_value.status = WorkflowExecutionStatus.FAILED
            failed = await session.call_tool("get_answer", {"run_id": run["run_id"]})
            assert json.loads(failed.content[0].text)["status"] == "FAILED"
            assert handle.result.await_count == 1
        tasks.cancel_scope.cancel()


async def test_temporal_client_uses_settings(monkeypatch):
    monkeypatch.setenv("TEMPORAL_ADDRESS", "custom-temporal:7233")
    connect = AsyncMock()
    monkeypatch.setattr(server.Client, "connect", connect)

    assert await server.temporal_client() is connect.return_value
    connect.assert_awaited_once_with("custom-temporal:7233")
