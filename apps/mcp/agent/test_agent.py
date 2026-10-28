from dataclasses import asdict
from unittest.mock import AsyncMock, Mock

import pytest
from temporalio.converter import DataConverter

from apps.mcp.agent.activities import AnswerActivities
from apps.mcp.agent.models import (
    AnswerRequest,
    AnswerResult,
    ArticleEvidence,
    Paragraph,
    SynthesisInput,
)
from backend.config import Settings
from backend.repositories.kilt import ElasticsearchKiltRepository
from backend.services.answer_synthesis.answer_synthesis import (
    AnswerSynthesisService,
    ExtractiveSynthesis,
)
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
    es.search.return_value["hits"]["hits"][0]["_source"] = es.get.return_value[
        "_source"
    ]
    service = KiltService(ElasticsearchKiltRepository(es, "kilt-v1"))
    evidences = await service.asearch_evidences("Arthur's Magazine", 1)
    paragraphs = [vars(p) for e in evidences for p in e.citation_paragraphs()]
    assert paragraphs == [await service.aget_paragraph("42", i) for i in range(3)]
    assert paragraphs[1]["paragraph_ref"] == "kilt-v1:42:1"
    assert paragraphs[0]["wikipedia_id"] == "123"
    assert paragraphs[1]["paragraph_id"] == 1


async def test_abstention_and_forged_citations():
    assert (
        await ExtractiveSynthesis().synthesize(SynthesisInput("question", []))
    ).abstained
    p = Paragraph("v:1:0", "v", "1", 0, "Title", "Original text")
    forged = Paragraph("v:1:0", "v", "1", 0, "Title", "Fabricated text")
    activities = AnswerActivities(
        Mock(),
        AnswerSynthesisService(
            Mock(
                synthesize=AsyncMock(return_value=AnswerResult("answer", "", [forged]))
            )
        ),
    )
    assert (await activities.agenerate(SynthesisInput("question", [p]))).abstained
    result = await ExtractiveSynthesis().synthesize(SynthesisInput("question", [p]))
    assert result.short_answer == p.text
    assert result.citations == [p]


async def test_temporal_result_round_trip():
    result = AnswerResult(
        "text", "explanation", [Paragraph("v:1:0", "v", "1", 0, "Title", "text")]
    )
    converter = DataConverter.default
    payloads = await converter.encode([result])
    assert await converter.decode(payloads, [AnswerResult]) == [result]


@pytest.mark.parametrize("question,limit", [(" ", 5), ("q", 0), ("q", 101)])
def test_request_validation(question, limit):
    with pytest.raises(ValueError):
        AnswerRequest(question, limit).validate()


@pytest.mark.parametrize("ceiling,overhead", [(180, 30), (240, 45)])
async def test_workflow_retrieves_synthesizes_then_verifies(
    monkeypatch, ceiling, overhead
):
    from apps.mcp.agent import workflow as module

    p = Paragraph("v:1:0", "v", "1", 0, "Title", "Evidence")
    calls = []

    async def execute(name, argument, **kwargs):
        calls.append(name)
        if name == "retrieve_answer_evidence":
            return [ArticleEvidence("1", "v", "1", "Title", [p.text])]
        if name == "record_answer_result":
            assert argument.answer.citations == [p]
            assert argument.session_id == "codex:chat-a"
            return None
        assert kwargs["retry_policy"].maximum_attempts == 3
        assert kwargs["start_to_close_timeout"].total_seconds() == ceiling + overhead
        assert (
            kwargs["schedule_to_close_timeout"].total_seconds()
            == 3 * (ceiling + overhead) + overhead
        )
        if name == "verify_answer":
            assert argument.answer.citations == [p]
            assert argument.session_id == "codex:chat-a"
            return argument.answer
        assert argument.citation_paragraphs() == [p]
        assert argument.session_id == "codex:chat-a"
        return await ExtractiveSynthesis().synthesize(argument)

    monkeypatch.setattr(module.workflow, "execute_activity", execute)
    result = await module.AnswerWorkflow().run(
        AnswerRequest(
            "question",
            session_id="codex:chat-a",
            timeout_settings=Settings(
                timeout_model_request_max_seconds=ceiling,
                timeout_activity_overhead_seconds=overhead,
            ).timeout_snapshot(),
        )
    )
    assert calls == [
        "retrieve_answer_evidence",
        "synthesize_answer",
        "verify_answer",
        "record_answer_result",
    ]
    assert result.citations == [p]
    assert "retrieved_evidences" not in asdict(result)


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


async def test_workflow_skips_verification_for_abstention(monkeypatch):
    from apps.mcp.agent import workflow as module

    candidate = AnswerResult("", "No evidence", abstained=True)
    execute = AsyncMock(side_effect=[[], candidate, None])
    monkeypatch.setattr(module.workflow, "execute_activity", execute)
    assert await module.AnswerWorkflow().run(AnswerRequest("question")) == candidate
    assert execute.await_count == 3


async def test_workflow_preserves_article_candidates_before_paragraph_filtering(
    monkeypatch,
):
    from apps.mcp.agent import workflow as module
    from apps.mcp.agent.models import ArticleCandidates

    paragraph = Paragraph("v:1:0", "v", "1", 0, "Title", "Evidence")
    candidates = ArticleCandidates(["1", "2"], 100, "v")
    evidences = [
        ArticleEvidence("1", "v", "1", "Title", [paragraph.text]),
        ArticleEvidence("2", "v", "2", "Other", []),
    ]

    async def execute(name, argument, **kwargs):
        if name == "retrieve_answer_evidence":
            return evidences
        if name == "synthesize_answer":
            assert argument.evidences == evidences
            assert argument.paragraphs == []
            return AnswerResult("", "Insufficient evidence", abstained=True)
        assert argument.answer.article_candidates == candidates

    monkeypatch.setattr(module.workflow, "execute_activity", execute)
    result = await module.AnswerWorkflow().run(AnswerRequest("question", limit=100))
    assert result.article_candidates == candidates
    assert "retrieved_evidences" not in asdict(result)
    converter = DataConverter.default
    encoded = await converter.encode([evidences])
    assert await converter.decode(encoded, [list[ArticleEvidence]]) == [evidences]
    encoded = await converter.encode([result])
    assert await converter.decode(encoded, [AnswerResult]) == [result]
