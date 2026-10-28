from unittest.mock import AsyncMock

from backend.repositories.kilt import ElasticsearchKiltRepository


async def test_import_is_lazy_preserves_source_and_counts_conflicts(monkeypatch):
    client = AsyncMock()
    client.indices.exists.return_value = False
    repository = ElasticsearchKiltRepository(client, "snapshot")
    source = {
        "_id": "42",
        "wikipedia_title": "Title",
        "categories": "Physics,Scattering, absorption",
        "text": ["Section::::History.:Origins.", "BULLET::::- Original"],
        "anchors": [{"offset": 3}],
    }
    consumed = []

    def documents():
        consumed.append(True)
        yield source

    async def streaming_bulk(es, actions, **kwargs):
        assert es is client
        assert kwargs["chunk_size"] == 2
        assert consumed == []
        action = next(actions)
        assert action["_index"] == "snapshot"
        assert action["_id"] == "42"
        assert "_id" not in action["_source"]
        assert action["_source"]["categories"] == ["Physics", "Scattering, absorption"]
        assert action["_source"]["sections"] == ["History", "Origins"]
        assert action["_source"]["text"] == source["text"]
        assert action["_source"]["anchors"] == source["anchors"]
        yield True, {"create": {"status": 201}}
        yield False, {"create": {"status": 409}}
        yield False, {"create": {"status": 500}}

    monkeypatch.setattr(
        "backend.repositories.kilt.helpers.async_streaming_bulk", streaming_bulk
    )
    assert await repository.aimport_documents(documents(), batch_size=2) == (1, 1, 1)
    client.indices.create.assert_awaited_once()
    assert isinstance(source["categories"], str)
    assert "sections" not in source


async def test_search_returns_complete_ranked_articles_without_gets():
    client = AsyncMock()
    client.search.return_value = {
        "hits": {
            "hits": [
                {
                    "_id": "internal-id",
                    "_score": 3.5,
                    "_source": {
                        "wikipedia_id": "123",
                        "wikipedia_title": "Article",
                        "text": ["Section::::History.", "", "Full text."],
                    },
                },
                {
                    "_id": "456",
                    "_score": 2.0,
                    "_source": {"wikipedia_title": "Other", "text": ["Other text."]},
                },
            ]
        }
    }
    hits = await ElasticsearchKiltRepository(client).asearch("question", 100)
    assert [h.wikipedia_id for h in hits] == ["123", "456"]
    assert hits[0].paragraphs == ("Section::::History.", "", "Full text.")
    assert hits[0].score == 3.5
    assert hits[0].paragraph("kilt", 2).paragraph_ref == "kilt:internal-id:2"
    client.search.assert_awaited_once()
    assert client.search.call_args.kwargs["source"] == [
        "wikipedia_title",
        "wikipedia_id",
        "text",
    ]
    client.get.assert_not_awaited()
