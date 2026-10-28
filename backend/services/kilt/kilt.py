"""KILT import orchestration and original-paragraph retrieval."""

import asyncio
import json
from collections.abc import Iterable, Iterator
from itertools import islice

from backend.domains.kilt import ArticleEvidence
from backend.repositories.kilt import KiltRepository


class KiltService:
    def __init__(self, repository: KiltRepository):
        self._repository = repository

    @property
    def corpus_version(self) -> str:
        return self._repository.corpus_version

    def parse_json(self, file_path: str, limit: int | None = 10) -> Iterator[dict]:
        """Stream records from a JSON Lines file one at a time.

        The KILT knowledge source is ~37GB, so it is never loaded whole.
        Pass limit=None to read the entire file.
        """
        with open(file_path, encoding="utf-8") as f:
            for line_number, line in enumerate(islice(f, limit), start=1):
                if not line.strip():
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as e:
                    raise ValueError(
                        f"Invalid JSON in {file_path}: line {line_number}, "
                        f"column {e.colno}: {e.msg}"
                    ) from e

    async def aimport_documents(
        self, documents: Iterable[dict], batch_size: int = 500
    ) -> tuple[int, int, int]:
        return await self._repository.aimport_documents(documents, batch_size)

    async def asearch(self, query: str, limit: int = 10) -> list[dict]:
        self._validate_search(query, limit)
        hits = await self._repository.asearch(query, limit)
        return [hit.model_dump(mode="json") for hit in hits]

    async def aget_paragraph(self, article_id: str, paragraph_id: int) -> dict:
        if paragraph_id < 0:
            raise ValueError("paragraph_id must be non-negative")
        article = await self._repository.aget_article(article_id)
        return article.paragraph(
            self._repository.corpus_version, paragraph_id
        ).model_dump()

    async def asearch_evidences(
        self, query: str, limit: int = 100
    ) -> list[ArticleEvidence]:
        """Return one complete evidence per article in search rank order."""
        self._validate_search(query, limit)
        articles = await self._repository.asearch(query, limit)
        return [
            ArticleEvidence(
                article_id=article.id,
                corpus_version=self._repository.corpus_version,
                wikipedia_id=article.wikipedia_id,
                title=article.title,
                paragraphs=list(article.paragraphs),
            )
            for article in articles
        ]

    @staticmethod
    def _validate_search(query: str, limit: int) -> None:
        if not query.strip():
            raise ValueError("query must not be empty")
        if limit < 1:
            raise ValueError("limit must be at least 1")


async def _main() -> None:
    from pprint import pprint

    from elasticsearch import AsyncElasticsearch

    from backend.repositories.kilt import ElasticsearchKiltRepository

    async with AsyncElasticsearch("http://localhost:9200") as client:
        service = KiltService(ElasticsearchKiltRepository(client))
        pprint(await service.asearch("top gun"))


if __name__ == "__main__":
    asyncio.run(_main())
