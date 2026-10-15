from unittest.mock import AsyncMock, Mock

import pytest
from temporalio.converter import DataConverter

from apps.mcp.agent.activities import AnswerActivities, aextractive_synthesis
from apps.mcp.agent.models import AnswerRequest, AnswerResult, Passage, SynthesisInput
from backend.repositories.kilt import ElasticsearchKiltRepository
from backend.services.kilt.kilt import KiltService


async def test_original_paragraph_identity():
    es = AsyncMock()
    es.search.return_value = {
        "hits": {
            "hits": [
                {"_id": "42", "_score": 1, "_source": {"wikipedia_title": "Magazine"}}
            ]
        }
    }
    es.get.return_value = {
        "_source": {
            "wikipedia_id": "123",
            "wikipedia_title": "Magazine",
            "text": [
                "Section::::History.",
                "Arthur's Magazine began in 1844.",
                "Other.",
            ],
        }
    }
    service = KiltService(ElasticsearchKiltRepository(es, "kilt-v1"))
    passages = await service.aretrieve_passages("Arthur's Magazine", 1)
    assert passages == [await service.aget_passage("42", 1)]
    assert passages[0]["passage_id"] == "kilt-v1:42:1"
    assert passages[0]["wikipedia_id"] == "123"
    assert passages[0]["paragraph_id"] == 1


async def test_abstention_and_forged_citations():
    assert (await aextractive_synthesis(SynthesisInput("question", []))).abstained
    p = Passage("v:1:0", "v", "1", 0, "Title", "Original text")
    forged = Passage("v:1:0", "v", "1", 0, "Title", "Fabricated text")
    activities = AnswerActivities(
        Mock(), AsyncMock(return_value=AnswerResult("answer", "", [forged]))
    )
    assert (await activities.agenerate(SynthesisInput("question", [p]))).abstained
    result = await aextractive_synthesis(SynthesisInput("question", [p]))
    assert result.short_answer == p.text
    assert result.citations == [p]


async def test_temporal_result_round_trip():
    result = AnswerResult(
        "text", "explanation", [Passage("v:1:0", "v", "1", 0, "Title", "text")]
    )
    converter = DataConverter.default
    payloads = await converter.encode([result])
    assert await converter.decode(payloads, [AnswerResult]) == [result]


@pytest.mark.parametrize("question,limit", [(" ", 5), ("q", 0), ("q", 11)])
def test_request_validation(question, limit):
    with pytest.raises(ValueError):
        AnswerRequest(question, limit).validate()


async def test_workflow_retrieves_before_synthesis(monkeypatch):
    from apps.mcp.agent import workflow as module

    p = Passage("v:1:0", "v", "1", 0, "Title", "Evidence")
    calls = []

    async def execute(name, argument, **kwargs):
        calls.append(name)
        if name == "retrieve_answer_evidence":
            return [p]
        assert argument.passages == [p]
        assert argument.session_id == "codex:chat-a"
        return await aextractive_synthesis(argument)

    monkeypatch.setattr(module.workflow, "execute_activity", execute)
    result = await module.AnswerWorkflow().run(
        AnswerRequest("question", session_id="codex:chat-a")
    )
    assert calls == ["retrieve_answer_evidence", "synthesize_answer"]
    assert result.citations == [p]


async def test_mcp_polling(monkeypatch):
    from temporalio.client import WorkflowExecutionStatus

    from apps.mcp import server

    handle = Mock()
    handle.describe = AsyncMock(
        return_value=Mock(status=WorkflowExecutionStatus.RUNNING)
    )
    handle.result = AsyncMock(return_value=AnswerResult("evidence", "quote"))
    client = Mock()
    client.get_workflow_handle.return_value = handle
    client.start_workflow = AsyncMock()
    monkeypatch.setattr(server, "temporal_client", AsyncMock(return_value=client))
    started = await server.answer("question")
    assert started["status"] == "RUNNING"
    pending = await server.get_answer(started["run_id"])
    assert "result" not in pending
    handle.result.assert_not_awaited()
    handle.describe.return_value.status = WorkflowExecutionStatus.COMPLETED
    completed = await server.get_answer(started["run_id"])
    assert completed["result"]["short_answer"] == "evidence"
