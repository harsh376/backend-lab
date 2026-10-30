"""Passage ranking contracts and interchangeable ranker implementations."""

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass

from backend.config import Settings
from backend.domains.kilt import Paragraph
from backend.repositories.kilt_ranking import score_paragraphs


@dataclass(frozen=True)
class RankedCandidate:
    paragraph: Paragraph
    # Zero-based retrieval position of the paragraph's article.
    article_rank: int


class PassageRanker(ABC):
    """Score candidate paragraphs for a question; higher scores rank first."""

    name: str

    @abstractmethod
    async def score(
        self, question: str, candidates: list[RankedCandidate]
    ) -> list[float]:
        """Return one score per candidate, aligned with the input order."""
        ...


class BM25PassageRanker(PassageRanker):
    """Candidate-local BM25 over paragraph windows; ignores article rank."""

    name = "bm25"

    async def score(
        self, question: str, candidates: list[RankedCandidate]
    ) -> list[float]:
        return await asyncio.to_thread(
            score_paragraphs,
            question,
            [(c.paragraph.title, c.paragraph.text) for c in candidates],
        )


_PASSAGE_RANKERS: dict[str, type[PassageRanker]] = {
    BM25PassageRanker.name: BM25PassageRanker,
}


def create_passage_ranker(settings: Settings) -> PassageRanker:
    """Resolve the configured ranker once, like synthesis services."""
    return _PASSAGE_RANKERS[settings.mcp_answer_passage_ranker]()
