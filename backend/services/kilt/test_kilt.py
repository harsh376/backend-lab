from unittest.mock import AsyncMock

import pytest

from backend.domains.kilt import KiltArticle, KiltSearchHit
from backend.services.kilt.kilt import KiltService


async def test_ranking_preserves_original_offsets_and_stable_ties():
    repository = AsyncMock()
    repository.corpus_version = "snapshot"
    repository.asearch.return_value = [KiltSearchHit(id="42", title="Article", score=1)]
    repository.aget_article.return_value = KiltArticle(
        id="42",
        wikipedia_id="123",
        title="Article",
        paragraphs=("Section::::cats dogs.", "", "cats", "cats dogs", "dogs cats"),
    )
    passages = await KiltService(repository).aretrieve_passages("cats dogs", 3)
    assert [p["paragraph_id"] for p in passages] == [3, 4, 2]
    assert passages[0]["passage_id"] == "snapshot:42:3"
    assert passages[0]["wikipedia_id"] == "123"
    assert passages[0]["text"] == "cats dogs"


@pytest.mark.parametrize("query,limit", [(" ", 1), ("cats", 0)])
async def test_invalid_search_does_not_call_repository(query, limit):
    repository = AsyncMock()
    service = KiltService(repository)
    with pytest.raises(ValueError):
        await service.asearch(query, limit)
    with pytest.raises(ValueError):
        await service.aretrieve_passages(query, limit)
    repository.asearch.assert_not_awaited()


def test_parse_json_is_lazy_and_reports_line_number(tmp_path):
    path = tmp_path / "articles.jsonl"
    path.write_text('{"_id": "1"}\ninvalid\n')
    service = KiltService(AsyncMock())
    assert list(service.parse_json(str(path), limit=1)) == [{"_id": "1"}]
    records = service.parse_json(str(path), limit=None)
    assert next(records) == {"_id": "1"}
    with pytest.raises(ValueError, match="line 2"):
        next(records)
