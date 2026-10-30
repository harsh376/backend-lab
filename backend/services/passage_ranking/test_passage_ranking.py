import pytest

from backend.config import Settings
from backend.domains.kilt import ArticleEvidence, Paragraph
from backend.repositories.kilt_ranking import score_paragraphs
from backend.services.answer_synthesis.answer_synthesis import (
    CompactArticleSynthesisService,
    SynthesisInput,
)
from backend.services.passage_ranking.passage_ranking import (
    BM25PassageRanker,
    PassageRanker,
    RankedCandidate,
    create_passage_ranker,
)


def paragraph(page, offset, text, title="Magazine"):
    return Paragraph(f"v:{page}:{offset}", "v", page, offset, title, text)


class RecordingRanker(PassageRanker):
    """Prefers later candidates so selection order is observable."""

    name = "recording"

    def __init__(self):
        self.calls = []

    async def score(self, question, candidates):
        self.calls.append((question, candidates))
        return [float(i) for i in range(len(candidates))]


def compact(ranker, **overrides):
    config = Settings(
        _env_file=None,
        mcp_answer_model="ollama_chat/qwen3.8",
        **overrides,
    )
    return CompactArticleSynthesisService(config, passage_ranker=ranker)


async def test_bm25_ranker_matches_window_scorer():
    candidates = [
        RankedCandidate(paragraph("1", 0, "The magazine began in 1844."), 0),
        RankedCandidate(paragraph("2", 3, "Gardens and trees.", "Garden"), 1),
    ]
    question = "When did the magazine begin?"
    scores = await BM25PassageRanker().score(question, candidates)
    assert scores == score_paragraphs(
        question, [(c.paragraph.title, c.paragraph.text) for c in candidates]
    )
    assert scores[0] > scores[1]
    assert await BM25PassageRanker().score(question, []) == []


def test_factory_resolves_configured_ranker():
    ranker = create_passage_ranker(Settings(_env_file=None))
    assert isinstance(ranker, BM25PassageRanker)
    assert ranker.name == "bm25"


def test_compact_defaults_to_configured_ranker():
    service = CompactArticleSynthesisService(
        Settings(_env_file=None, mcp_answer_model="ollama_chat/qwen3.8")
    )
    assert isinstance(service.passage_ranker, BM25PassageRanker)


async def test_compact_passes_article_rank_in_evidence_order():
    ranker = RecordingRanker()
    data = SynthesisInput(
        "question",
        evidences=[
            ArticleEvidence("a", "v", "10", "First", ["Section::::Lead.", "One"]),
            ArticleEvidence("b", "v", "20", "Second", ["", "Two", "Three"]),
        ],
    )
    await compact(ranker).prepare_input(data)
    [(question, candidates)] = ranker.calls
    assert question == "question"
    # Section markers and empty paragraphs are filtered before ranking.
    assert [(c.paragraph.paragraph_ref, c.article_rank) for c in candidates] == [
        ("v:a:1", 0),
        ("v:b:1", 1),
        ("v:b:2", 1),
    ]


async def test_compact_ranks_paragraph_input_by_first_article_appearance():
    ranker = RecordingRanker()
    paragraphs = [
        paragraph("2", 4, "Beta"),
        paragraph("1", 0, "Alpha"),
        paragraph("2", 1, "Gamma"),
    ]
    await compact(ranker).prepare_input(SynthesisInput("question", paragraphs))
    [(_, candidates)] = ranker.calls
    assert [c.article_rank for c in candidates] == [0, 1, 0]


async def test_compact_selects_by_injected_ranker_scores():
    paragraphs = [paragraph("1", i, f"Paragraph {i}") for i in range(4)]
    service = compact(RecordingRanker(), mcp_answer_context_max_paragraphs=2)
    prepared = await service.prepare_input(SynthesisInput("question", paragraphs))
    # Highest scores are the last two candidates; output keeps original order.
    assert [p.paragraph_id for p in prepared.paragraphs] == [2, 3]


@pytest.mark.parametrize("value", ["unknown", ""])
def test_invalid_ranker_setting_is_rejected(monkeypatch, value):
    from pydantic import ValidationError

    monkeypatch.setenv("MCP_ANSWER_PASSAGE_RANKER", value)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
