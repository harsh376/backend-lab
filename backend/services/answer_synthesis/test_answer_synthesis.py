import json
from dataclasses import replace
from unittest.mock import AsyncMock, Mock

import httpx
import litellm
import pytest

from backend.config import Settings
from backend.llm import ModelProviderError
from backend.services.answer_synthesis.answer_synthesis import (
    AnswerResult,
    AnswerSynthesisService,
    CompactArticleSynthesisService,
    ExtractiveSynthesisService,
    FullArticleSynthesisService,
    Paragraph,
    SynthesisInput,
    create_synthesis_service,
)


@pytest.fixture
def evidence():
    return Paragraph("v:1:0", "v", "1", 0, "Magazine", "It began in 1844.")


@pytest.fixture
def completion(monkeypatch, evidence):
    response = litellm.ModelResponse(
        model="returned-model",
        choices=[
            {
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": json.dumps(
                        {
                            "short_answer": "1844",
                            "explanation": "The magazine began in 1844.",
                            "citation_ids": [evidence.paragraph_ref],
                            "abstained": False,
                        }
                    ),
                },
            }
        ],
        usage={"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
    )
    call = AsyncMock(return_value=response)
    monkeypatch.setattr(litellm, "acompletion", call)
    monkeypatch.setattr(litellm, "completion_cost", Mock(return_value=0.001))
    return call


def settings(model="openai/gpt-5.6-terra"):
    return Settings(
        mcp_answer_model=model,
        openai_api_key="test-openai-key",
        anthropic_api_key="test-anthropic-key",
    )


@pytest.mark.parametrize(
    "model,key",
    [
        ("openai/gpt-5.6-terra", "test-openai-key"),
        ("anthropic/claude-sonnet-5", "test-anthropic-key"),
    ],
)
@pytest.mark.parametrize(
    "mode,adapter_class,prompt_version",
    [
        ("full", FullArticleSynthesisService, "article-synthesis-v3"),
        ("compact", CompactArticleSynthesisService, "compact-synthesis-v1"),
    ],
)
async def test_provider_selection_and_original_citations(
    completion, evidence, model, key, mode, adapter_class, prompt_version
):
    config = settings(model).model_copy(update={"mcp_answer_context_mode": mode})
    adapter = create_synthesis_service(config)
    assert isinstance(adapter, adapter_class)
    synthesize = adapter
    result = await synthesize.synthesize(
        SynthesisInput("When did it begin?", [evidence])
    )
    assert result.short_answer == "1844"
    assert result.citations == [evidence]
    assert result.citations[0] is evidence
    assert result.provider == model.split("/")[0]
    assert result.model == model
    assert result.usage == {
        "prompt_tokens": 100,
        "completion_tokens": 20,
        "total_tokens": 120,
    }
    assert result.usage_cost_usd == 0.001
    args = completion.call_args.kwargs
    assert args["model"] == model
    assert args["messages"][0]["content"] == adapter.system_prompt
    assert adapter.prompt_version == prompt_version
    assert args["api_key"] == key
    assert args["num_retries"] == 0
    assert args["caching"] is False
    assert args["timeout"] == settings(model).timeout_model_request_seconds
    assert args["timeout"] < settings(model).timeout_model_activity_seconds
    assert args["response_format"]["json_schema"]["strict"] is True
    assert json.loads(args["messages"][1]["content"])["articles"][0]["paragraphs"][0][
        "text"
    ] == (evidence.text)


@pytest.mark.parametrize(
    "content,finish",
    [
        ("not json", "stop"),
        ('{"short_answer":"1844"}', "stop"),
        (None, "stop"),
        ("{}", "length"),
        ("{}", "content_filter"),
        (
            json.dumps(
                {
                    "short_answer": "1844",
                    "explanation": "x",
                    "citation_ids": ["invented"],
                    "abstained": False,
                }
            ),
            "stop",
        ),
        (
            json.dumps(
                {
                    "short_answer": "1844",
                    "explanation": "x",
                    "citation_ids": [],
                    "abstained": False,
                }
            ),
            "stop",
        ),
        (
            json.dumps(
                {
                    "short_answer": " ",
                    "explanation": "x",
                    "citation_ids": ["v:1:0"],
                    "abstained": False,
                }
            ),
            "stop",
        ),
        (
            json.dumps(
                {
                    "short_answer": "1844",
                    "explanation": "insufficient evidence",
                    "citation_ids": ["v:1:0"],
                    "abstained": True,
                }
            ),
            "stop",
        ),
    ],
)
async def test_unusable_answers_abstain_without_losing_usage(
    completion, evidence, content, finish
):
    completion.return_value.choices[0].message.content = content
    completion.return_value.choices[0].finish_reason = finish
    result = await create_synthesis_service(settings()).synthesize(
        SynthesisInput("question", [evidence])
    )
    assert result.abstained
    assert result.short_answer == ""
    assert result.citations == []
    assert result.usage["total_tokens"] == 120
    assert result.usage_cost_usd == 0.001


async def test_no_evidence_skips_provider(completion):
    result = await create_synthesis_service(settings()).synthesize(
        SynthesisInput("question", [])
    )
    assert result.abstained
    assert result.usage == {}
    assert result.usage_cost_usd is None
    completion.assert_not_awaited()


async def test_unknown_pricing_keeps_answer(completion, evidence, monkeypatch):
    monkeypatch.setattr(
        litellm, "completion_cost", Mock(side_effect=ValueError("unknown"))
    )
    result = await create_synthesis_service(settings()).synthesize(
        SynthesisInput("question", [evidence])
    )
    assert result.short_answer == "1844"
    assert result.usage_cost_usd is None


@pytest.mark.parametrize("model", ["gpt-5.6-terra", "openai/", "gemini/model"])
def test_invalid_provider_configuration(model):
    with pytest.raises(ValueError, match="MCP_ANSWER_MODEL"):
        create_synthesis_service(settings(model))


@pytest.mark.parametrize(
    "provider,key_field",
    [
        ("openai", "openai_api_key"),
        ("anthropic", "anthropic_api_key"),
    ],
)
def test_missing_credentials(provider, key_field):
    config = settings(f"{provider}/model")
    setattr(config, key_field, None)
    with pytest.raises(ValueError, match="API_KEY"):
        create_synthesis_service(config)
    assert "test-openai-key" not in repr(settings())
    assert "test-anthropic-key" not in repr(settings())
    assert "test-openai-key" not in repr(create_synthesis_service(settings()))


async def test_authentication_error_is_not_retried(completion, evidence):
    completion.side_effect = litellm.AuthenticationError(
        message="sensitive provider message", llm_provider="openai", model="model"
    )
    with pytest.raises(ModelProviderError) as caught:
        await create_synthesis_service(settings()).synthesize(
            SynthesisInput("question", [evidence])
        )
    assert caught.value.error_type == "AuthenticationError"
    assert "sensitive" not in str(caught.value)
    completion.assert_awaited_once()


async def test_transient_error_reaches_caller(completion, evidence):
    error = litellm.Timeout(message="timeout", model="model", llm_provider="openai")
    completion.side_effect = error
    with pytest.raises(litellm.Timeout):
        await create_synthesis_service(settings()).synthesize(
            SynthesisInput("question", [evidence])
        )
    completion.assert_awaited_once()


@pytest.mark.parametrize(
    "model,host",
    [
        ("openai/gpt-5.6-terra", "api.openai.com"),
        ("anthropic/claude-sonnet-5", "api.anthropic.com"),
    ],
)
@pytest.mark.parametrize("status", [200, 429])
async def test_real_litellm_provider_translation(
    monkeypatch, evidence, model, host, status
):
    """Exercise LiteLLM itself with HTTP stubbed at the transport boundary."""
    content = json.dumps(
        {
            "short_answer": "1844",
            "explanation": "It began in 1844.",
            "citation_ids": [evidence.paragraph_ref],
            "abstained": False,
        }
    )
    requests = []

    async def send(client, request, **kwargs):
        requests.append(request)
        assert request.url.host == host
        if status == 429:
            return httpx.Response(
                429,
                json={"error": {"type": "rate_limit_error", "message": "Rate limited"}},
                request=request,
            )
        body = json.loads(request.content)
        assert body["model"] == model.split("/", 1)[1]
        if model.startswith("openai/"):
            assert body["response_format"]["json_schema"]["strict"] is True
            payload = {
                "id": "chatcmpl-stub",
                "object": "chat.completion",
                "created": 1,
                "model": body["model"],
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": content},
                    }
                ],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 20,
                    "total_tokens": 120,
                },
            }
        else:
            assert body.get("output_format") or body.get("output_config")
            payload = {
                "id": "msg-stub",
                "type": "message",
                "role": "assistant",
                "model": body["model"],
                "content": [{"type": "text", "text": content}],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 100, "output_tokens": 20},
            }
        return httpx.Response(200, json=payload, request=request)

    monkeypatch.setattr(httpx.AsyncClient, "send", send)
    synthesize = create_synthesis_service(settings(model))
    data = SynthesisInput("When did it begin?", [evidence])
    if status == 429:
        with pytest.raises(litellm.RateLimitError):
            await synthesize.synthesize(data)
    else:
        result = await synthesize.synthesize(data)
        assert result.short_answer == "1844"
        assert result.citations == [evidence]
        assert result.usage["prompt_tokens"] == 100
        assert result.usage["completion_tokens"] == 20
    assert len(requests) == 1


async def test_extractive_service():
    service = ExtractiveSynthesisService()
    empty = await service.synthesize(SynthesisInput("question", []))
    assert empty.abstained
    paragraph = Paragraph("v:1:0", "v", "1", 0, "Title", "Original text")
    result = await service.synthesize(SynthesisInput("question", [paragraph]))
    assert result.short_answer == paragraph.text
    assert result.citations == [paragraph]
    assert result.usage == {}
    assert result.usage_cost_usd is None


async def test_custom_service_shares_citation_validation():
    paragraph = Paragraph("v:1:0", "v", "1", 0, "Title", "Original text")

    class CustomSynthesis(AnswerSynthesisService):
        async def _synthesize(self, data: SynthesisInput) -> AnswerResult:
            assert data.question == "question"
            return AnswerResult(
                "answer", "explanation", data.paragraphs, provider="custom"
            )

    result = await CustomSynthesis().synthesize(SynthesisInput("question", [paragraph]))
    assert result.provider == "custom"
    assert result.short_answer == "answer"
    assert result.citations[0] is paragraph


@pytest.mark.parametrize("variation", ["forged", "missing", "empty", "abstained"])
async def test_shared_validation_preserves_accounting(variation):
    paragraph = Paragraph("v:1:0", "v", "1", 0, "Title", "Original text")
    result = AnswerResult(
        "answer",
        "explanation",
        [paragraph],
        provider="custom",
        model="custom/model",
        usage={"total_tokens": 120},
        usage_cost_usd=0.001,
    )
    if variation == "forged":
        result.citations = [replace(paragraph, text="Fabricated text")]
    elif variation == "missing":
        result.citations = []
    elif variation == "empty":
        result.short_answer = " "
    else:
        result.abstained = True

    class CustomSynthesis(AnswerSynthesisService):
        _synthesize = AsyncMock(return_value=result)

    service = CustomSynthesis()
    data = SynthesisInput("question", [paragraph])
    checked = await service.synthesize(data)
    service._synthesize.assert_awaited_once_with(data)
    assert checked.abstained
    assert checked.short_answer == ""
    assert checked.citations == []
    assert checked.provider == "custom"
    assert checked.model == "custom/model"
    assert checked.usage == {"total_tokens": 120}
    assert checked.usage_cost_usd == 0.001
    assert checked is not result


def test_prompt_groups_complete_articles_without_filtering():
    paragraphs = [
        Paragraph("v:1:0", "v", "1", 0, "One", "Section::::History."),
        Paragraph("v:1:1", "v", "1", 1, "One", ""),
        Paragraph("v:1:2", "v", "1", 2, "One", "Unrelated words still included."),
        Paragraph("v:2:0", "v", "2", 0, "Two", "Second article."),
    ]
    messages = FullArticleSynthesisService(settings())._build_messages(
        SynthesisInput("question", paragraphs)
    )
    payload = json.loads(messages[1]["content"])
    assert [a["wikipedia_id"] for a in payload["articles"]] == ["1", "2"]
    assert [p["text"] for p in payload["articles"][0]["paragraphs"]] == [
        "Section::::History.",
        "",
        "Unrelated words still included.",
    ]
    assert [
        p["paragraph_ref"] for a in payload["articles"] for p in a["paragraphs"]
    ] == [p.paragraph_ref for p in paragraphs]


def test_article_evidences_remain_separate_and_citations_keep_article_identity():
    from backend.services.answer_synthesis.answer_synthesis import ArticleEvidence

    evidences = [
        ArticleEvidence("10", "v", "123", "First", ["Heading", "", "Full body"]),
        ArticleEvidence("20", "v", "456", "Second", ["Other body"]),
    ]
    data = SynthesisInput(question="question", evidences=evidences)
    payload = json.loads(
        FullArticleSynthesisService(settings())._build_messages(data)[1]["content"]
    )
    assert [a["article_id"] for a in payload["articles"]] == ["10", "20"]
    assert [p["text"] for p in payload["articles"][0]["paragraphs"]] == [
        "Heading",
        "",
        "Full body",
    ]
    assert [p.paragraph_ref for p in data.citation_paragraphs()] == [
        "v:10:0",
        "v:10:1",
        "v:10:2",
        "v:20:0",
    ]


def compact_adapter(**overrides):
    config = settings().model_copy(
        update={
            "mcp_answer_context_mode": "compact",
            **overrides,
        }
    )
    return CompactArticleSynthesisService(config)


def test_compact_selects_deep_evidence_from_tenth_article_and_preserves_offsets():
    from backend.domains.kilt import ArticleEvidence

    articles = [
        ArticleEvidence(str(i), "v", str(i), "Unrelated", ["Gardens and trees."] * 20)
        for i in range(9)
    ]
    articles.append(
        ArticleEvidence(
            "9",
            "v",
            "9",
            "Magazine",
            [
                "Section::::History.",
                "",
                *["Gardens and trees."] * 30,
                "The magazine began in 1844.",
            ],
        )
    )
    data = SynthesisInput("When did the magazine begin?", evidences=articles)
    adapter = compact_adapter()
    prepared = adapter._prepare_input(data)
    assert any(p.paragraph_ref == "v:9:32" for p in prepared.paragraphs)
    assert len(prepared.paragraphs) <= 5
    assert len({p.text for p in prepared.paragraphs}) == len(prepared.paragraphs)
    assert all(
        p.text.strip() and not p.text.startswith("Section::::")
        for p in prepared.paragraphs
    )
    assert articles[9].paragraphs[32] == "The magazine began in 1844."
    assert len(articles[9].paragraphs) == 33
    assert data.evidences is articles
    assert adapter._context_tokens(prepared) <= 2000


def test_compact_budget_skips_oversized_paragraph_without_truncating_citations():
    paragraphs = [
        Paragraph("v:1:0", "v", "1", 0, "Magazine", "magazine began " * 5000),
        Paragraph("v:2:7", "v", "2", 7, "Magazine", "The magazine began in 1844."),
    ]
    adapter = compact_adapter(mcp_answer_context_max_tokens=700)
    data = SynthesisInput("When did the magazine begin?", paragraphs)
    prepared = adapter._prepare_input(data)
    assert prepared.paragraphs == [paragraphs[1]]
    assert prepared.paragraphs[0] is paragraphs[1]
    assert adapter._context_tokens(prepared) <= 700
    assert adapter._build_messages(data) == adapter._serialize_messages(prepared)


def test_compact_keeps_multiple_articles_and_original_paragraph_order():
    paragraphs = [
        Paragraph("v:1:8", "v", "1", 8, "One", "Alpha publisher is Acme."),
        Paragraph("v:1:2", "v", "1", 2, "One", "Alpha publisher was founded earlier."),
        Paragraph("v:2:4", "v", "2", 4, "Two", "Beta publisher is Acme."),
    ]
    adapter = compact_adapter(mcp_answer_context_max_paragraphs=2)
    prepared = adapter._prepare_input(
        SynthesisInput("Alpha Beta publisher", paragraphs)
    )
    assert {p.wikipedia_id for p in prepared.paragraphs} == {"1", "2"}
    adapter.context_max_paragraphs = 5
    prepared = adapter._prepare_input(
        SynthesisInput("Alpha Beta publisher", paragraphs)
    )
    assert [p.paragraph_id for p in prepared.paragraphs if p.wikipedia_id == "1"] == [
        2,
        8,
    ]


async def test_compact_rejects_citation_to_retrieved_but_omitted_paragraph(
    completion,
    evidence,
):
    other = replace(
        evidence,
        paragraph_ref="v:2:9",
        wikipedia_id="2",
        paragraph_id=9,
        text="Magazine magazine began in 1900.",
    )
    adapter = compact_adapter(mcp_answer_context_max_paragraphs=1)
    data = SynthesisInput("When did magazine magazine begin?", [evidence, other])
    selected = adapter._prepare_input(data).paragraphs
    omitted = next(p for p in [evidence, other] if p not in selected)
    content = json.loads(completion.return_value.choices[0].message.content)
    content["citation_ids"] = [omitted.paragraph_ref]
    completion.return_value.choices[0].message.content = json.dumps(content)
    result = await adapter.synthesize(data)
    assert result.abstained
    assert result.citations == []
    assert result.usage["total_tokens"] == 120
    assert completion.call_args.kwargs["messages"] == adapter._build_messages(data)


async def test_compact_no_fitting_context_skips_model(completion, evidence):
    adapter = compact_adapter(mcp_answer_context_max_tokens=1)
    result = await adapter.synthesize(SynthesisInput("When?", [evidence]))
    assert result.abstained
    completion.assert_not_awaited()


def test_full_mode_bypasses_compact_limits(evidence):
    config = settings().model_copy(
        update={
            "mcp_answer_context_mode": "full",
            "mcp_answer_context_max_tokens": 1,
            "mcp_answer_context_max_paragraphs": 1,
        }
    )
    adapter = FullArticleSynthesisService(config)
    paragraphs = [evidence, replace(evidence, paragraph_ref="v:1:1", paragraph_id=1)]
    data = SynthesisInput("When?", paragraphs)
    assert adapter._prepare_input(data) is data
    payload = json.loads(adapter._build_messages(data)[1]["content"])
    assert len(payload["articles"][0]["paragraphs"]) == 2


@pytest.mark.parametrize("mode", ["full", "compact"])
async def test_ollama_quote_and_generation_use_identical_article_context(
    completion,
    evidence,
    mode,
):
    from apps.mcp.agent.activities import AnswerActivities
    from backend.domains.kilt import ArticleEvidence

    config = settings("ollama_chat/qwen3.8").model_copy(
        update={"mcp_answer_context_mode": mode}
    )
    adapter = create_synthesis_service(config)
    adapter.model.quote = Mock(return_value=None)
    data = SynthesisInput(
        "When did the magazine begin?",
        evidences=[
            ArticleEvidence("1", "v", "1", "Magazine", [evidence.text]),
        ],
    )
    activities = AnswerActivities(Mock(), adapter)
    await activities.aquote_synthesis(data)
    result = await activities.agenerate(data)
    assert result.short_answer == "1844"
    assert (
        adapter.model.quote.call_args.args[0] == completion.call_args.kwargs["messages"]
    )
    if isinstance(adapter, CompactArticleSynthesisService):
        assert adapter._context_tokens(adapter._prepare_input(data)) <= 2000
