from unittest.mock import AsyncMock

import pytest

from backend.domains.kilt import KiltSearchHit
from backend.services.kilt.kilt import KiltService


async def test_complete_articles_preserve_all_paragraphs_and_offsets():
    repository = AsyncMock()
    repository.corpus_version = "snapshot"
    repository.asearch.return_value = [
        KiltSearchHit(
            id="42",
            wikipedia_id="123",
            title="Article",
            score=1,
            paragraphs=("Section::::cats dogs.", "", "cats", "cats dogs", "dogs cats"),
        )
    ]
    evidences = await KiltService(repository).asearch_evidences("cats dogs", 3)
    assert len(evidences) == 1
    paragraphs = evidences[0].citation_paragraphs()
    paragraphs = [vars(p) for p in paragraphs]
    assert [p["paragraph_id"] for p in paragraphs] == [0, 1, 2, 3, 4]
    assert paragraphs[0]["paragraph_ref"] == "snapshot:42:0"
    assert paragraphs[0]["wikipedia_id"] == "123"
    assert paragraphs[0]["text"] == "Section::::cats dogs."
    assert paragraphs[1]["text"] == ""


@pytest.mark.parametrize("query,limit", [(" ", 1), ("cats", 0)])
async def test_invalid_search_does_not_call_repository(query, limit):
    repository = AsyncMock()
    service = KiltService(repository)
    with pytest.raises(ValueError):
        await service.asearch(query, limit)
    with pytest.raises(ValueError):
        await service.asearch_evidences(query, limit)
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


async def test_candidates_include_articles_without_matching_paragraphs():
    repository = AsyncMock()
    repository.corpus_version = "snapshot"
    repository.asearch.return_value = [
        KiltSearchHit(
            id="42", wikipedia_id="123", title="Relevant", score=2, paragraphs=("cats",)
        ),
        KiltSearchHit(
            id="43", wikipedia_id="456", title="Other", score=1, paragraphs=("dogs",)
        ),
    ]
    evidences = await KiltService(repository).asearch_evidences("cats", 5)
    repository.asearch.assert_awaited_once_with("cats", 5)
    assert [e.wikipedia_id for e in evidences] == ["123", "456"]
    assert [e.paragraphs for e in evidences] == [["cats"], ["dogs"]]
    repository.aget_article.assert_not_awaited()
