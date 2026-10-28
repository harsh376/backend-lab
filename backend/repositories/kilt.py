"""KILT repository contract and Elasticsearch persistence."""

import logging
from collections.abc import Iterable, Iterator
from typing import Protocol

from elasticsearch import AsyncElasticsearch, helpers

from backend.domains.kilt import (
    KiltArticle,
    KiltSearchHit,
    extract_sections,
    split_categories,
)

logger = logging.getLogger(__name__)
HTTP_CONFLICT = 409

INDEX_SETTINGS = {
    "number_of_shards": 1,
    "number_of_replicas": 0,
    "analysis": {
        # Markers are stripped only for searching; the stored paragraphs are left
        # untouched because anchor offsets point into them.
        "char_filter": {
            "kilt_markers": {
                "type": "pattern_replace",
                "pattern": r"^(?:Section::::|BULLET::::(?:-|\d+\.)?\s*)",
                "replacement": "",
            }
        },
        "analyzer": {
            "kilt_text": {
                "type": "custom",
                "char_filter": ["kilt_markers"],
                "tokenizer": "standard",
                "filter": ["lowercase"],
            }
        },
    },
}

# Only these fields are searchable; the rest of each record is kept in _source.
INDEX_MAPPINGS = {
    "dynamic": False,
    "properties": {
        "wikipedia_id": {"type": "keyword"},
        "wikipedia_title": {
            "type": "text",
            "fields": {"keyword": {"type": "keyword", "ignore_above": 256}},
        },
        "text": {"type": "text", "analyzer": "kilt_text"},
        "sections": {
            "type": "text",
            "fields": {"keyword": {"type": "keyword", "ignore_above": 256}},
        },
        "categories": {"type": "keyword"},
    },
}


class KiltRepository(Protocol):
    @property
    def corpus_version(self) -> str: ...

    async def aimport_documents(
        self, documents: Iterable[dict], batch_size: int = 500
    ) -> tuple[int, int, int]: ...

    async def asearch(self, query: str, limit: int = 10) -> list[KiltSearchHit]: ...

    async def aget_article(self, article_id: str) -> KiltArticle: ...


class ElasticsearchKiltRepository:
    def __init__(self, client: AsyncElasticsearch, index_name: str = "kilt"):
        self._client = client
        self._index_name = index_name

    @property
    def corpus_version(self) -> str:
        return self._index_name

    async def aimport_documents(
        self, documents: Iterable[dict], batch_size: int = 500
    ) -> tuple[int, int, int]:
        """Bulk index documents in batches.

        Returns (indexed, skipped, failed) counts. Documents are consumed lazily,
        so a generator from parse_json can be passed straight in. Each record's
        _id is used as the document ID and documents are only ever created, so
        re-running the import skips the ones already indexed.
        """
        await self._acreate_index_if_missing()

        indexed = skipped = failed = 0
        results = helpers.async_streaming_bulk(
            self._client,
            self._actions(documents),
            chunk_size=batch_size,
            max_retries=3,
            raise_on_error=False,
        )
        async for ok, item in results:
            if ok:
                indexed += 1
            elif item["create"]["status"] == HTTP_CONFLICT:
                skipped += 1
            else:
                failed += 1
                logger.warning("Failed to index document: %s", item)
        return indexed, skipped, failed

    async def asearch(self, query: str, limit: int = 10) -> list[KiltSearchHit]:
        response = await self._client.search(
            index=self._index_name,
            query={
                "multi_match": {
                    "query": query,
                    # A title match counts for more than a match in the body.
                    "fields": ["wikipedia_title^3", "text"],
                }
            },
            highlight={
                "fields": {"text": {"number_of_fragments": 3, "fragment_size": 200}},
                # Elasticsearch refuses to highlight text longer than 1,000,000
                # characters, so truncate very long articles instead of failing.
                "max_analyzed_offset": 999_999,
            },
            source=["wikipedia_title", "wikipedia_id", "text"],
            size=limit,
        )
        return [
            KiltSearchHit(
                id=hit["_id"],
                wikipedia_id=str(hit["_source"].get("wikipedia_id", hit["_id"])),
                paragraphs=tuple(hit["_source"].get("text", [])),
                title=hit["_source"]["wikipedia_title"],
                score=hit["_score"],
                snippets=tuple(hit.get("highlight", {}).get("text", [])),
            )
            for hit in response["hits"]["hits"]
        ]

    async def aget_article(self, article_id: str) -> KiltArticle:
        response = await self._client.get(index=self._index_name, id=article_id)
        source = response["_source"]
        return KiltArticle(
            id=article_id,
            wikipedia_id=str(source.get("wikipedia_id", article_id)),
            title=source["wikipedia_title"],
            paragraphs=tuple(source.get("text", [])),
        )

    async def _acreate_index_if_missing(self) -> None:
        if await self._client.indices.exists(index=self._index_name):
            return
        await self._client.indices.create(
            index=self._index_name,
            settings=INDEX_SETTINGS,
            mappings=INDEX_MAPPINGS,
        )

    def _actions(self, documents: Iterable[dict]) -> Iterator[dict]:
        for document in documents:
            # _id is a metadata field and is rejected inside the document body.
            source = {key: value for key, value in document.items() if key != "_id"}
            if isinstance(source.get("categories"), str):
                source["categories"] = split_categories(source["categories"])
            source["sections"] = extract_sections(source.get("text", []))
            yield {
                "_op_type": "create",
                "_index": self._index_name,
                "_id": document["_id"],
                "_source": source,
            }
