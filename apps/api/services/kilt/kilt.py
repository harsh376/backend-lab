import asyncio
import json
import logging
import re
from collections.abc import Iterable, Iterator
from itertools import islice

from elasticsearch import AsyncElasticsearch, helpers

logger = logging.getLogger(__name__)

# Categories are joined by a bare comma; a comma followed by a space belongs to
# the category name, e.g. "Scattering, absorption and radiative transfer (optics)".
CATEGORY_SEPARATOR = re.compile(r",(?! )")

# Returned for a create when a document with that ID already exists.
HTTP_CONFLICT = 409

# Paragraphs carry structural markers: headings look like
# "Section::::History.:Typographic variants." and list items like "BULLET::::- "
# or "BULLET::::1. ".
SECTION_MARKER = "Section::::"
SECTION_PATH_SEPARATOR = ".:"

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


class KiltService:
    def __init__(self, client: AsyncElasticsearch, index_name: str = "kilt"):
        self._client = client
        self._index_name = index_name

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

    async def asearch(self, query: str, limit: int = 10) -> list[dict]:
        """Full-text search over article titles and text, best match first.

        Each result has the article's id, title, relevance score and up to three
        matching text snippets. The full document is not returned because
        articles are large; fetch it by id when needed.
        """
        if not query.strip():
            raise ValueError("query must not be empty")
        if limit < 1:
            raise ValueError("limit must be at least 1")

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
            source=["wikipedia_title"],
            size=limit,
        )
        return [
            {
                "id": hit["_id"],
                "title": hit["_source"]["wikipedia_title"],
                "score": hit["_score"],
                "snippets": hit.get("highlight", {}).get("text", []),
            }
            for hit in response["hits"]["hits"]
        ]

    async def aget_passage(self, article_id: str, paragraph_id: int) -> dict:
        """Fetch original text with a stable index/article/paragraph identity.

        Use an immutable, versioned index name to pin a corpus snapshot.
        """
        if paragraph_id < 0:
            raise ValueError("paragraph_id must be non-negative")
        response = await self._client.get(index=self._index_name, id=article_id)
        document = response["_source"]
        paragraphs = document.get("text", [])
        if paragraph_id >= len(paragraphs):
            raise ValueError("paragraph_id is out of range")
        return {
            "passage_id": f"{self._index_name}:{article_id}:{paragraph_id}",
            "corpus_version": self._index_name,
            "wikipedia_id": str(document.get("wikipedia_id", article_id)),
            "paragraph_id": paragraph_id,
            "title": document["wikipedia_title"],
            "text": paragraphs[paragraph_id],
        }

    async def aretrieve_passages(self, query: str, limit: int = 5) -> list[dict]:
        """Rank original paragraphs from matching articles by query-term overlap.

        Highlights are display fragments and cannot identify KILT paragraphs;
        fetch original text so citations preserve the dataset paragraph offsets.
        """
        terms = set(re.findall(r"\w+", query.lower()))
        passages = []
        hits = await self.asearch(query, limit)
        responses = await asyncio.gather(
            *(self._client.get(index=self._index_name, id=hit["id"]) for hit in hits)
        )
        for hit, response in zip(hits, responses, strict=True):
            document = response["_source"]
            for paragraph_id, paragraph in enumerate(document.get("text", [])):
                if not paragraph.strip() or paragraph.startswith(SECTION_MARKER):
                    continue
                overlap = len(terms & set(re.findall(r"\w+", paragraph.lower())))
                if not overlap:
                    continue
                passages.append(
                    (
                        overlap,
                        {
                            "passage_id": (
                                f"{self._index_name}:{hit['id']}:{paragraph_id}"
                            ),
                            "corpus_version": self._index_name,
                            "wikipedia_id": str(
                                document.get("wikipedia_id", hit["id"])
                            ),
                            "paragraph_id": paragraph_id,
                            "title": document["wikipedia_title"],
                            "text": paragraph,
                        },
                    )
                )
        passages.sort(key=lambda item: item[0], reverse=True)
        return [passage for _, passage in passages[:limit]]

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
                source["categories"] = self._split_categories(source["categories"])
            source["sections"] = self._extract_sections(source.get("text", []))
            yield {
                "_op_type": "create",
                "_index": self._index_name,
                "_id": document["_id"],
                "_source": source,
            }

    @staticmethod
    def _split_categories(categories: str) -> list[str]:
        parts = (part.strip() for part in CATEGORY_SEPARATOR.split(categories))
        return [part for part in parts if part]

    @staticmethod
    def _extract_sections(paragraphs: list[str]) -> list[str]:
        """Return the distinct heading names in order of first appearance."""
        sections: dict[str, None] = {}
        for paragraph in paragraphs:
            if not paragraph.startswith(SECTION_MARKER):
                continue
            path = paragraph.removeprefix(SECTION_MARKER).strip().removesuffix(".")
            for name in path.split(SECTION_PATH_SEPARATOR):
                if name.strip():
                    sections[name.strip()] = None
        return list(sections)


async def _main() -> None:
    from pprint import pprint

    async with AsyncElasticsearch("http://localhost:9200") as client:
        service = KiltService(client)
        # records = service.parse_json(
        #     "/Users/harsh/Desktop/kilt_knowledgesource.json"
        # )
        # indexed, skipped, failed = await service.aimport_documents(records)
        # print(
        #     f"Indexed {indexed} documents, {skipped} already existed, "
        #     f"{failed} failed"
        # )
        results = await service.asearch("top gun")
        pprint(results)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_main())
