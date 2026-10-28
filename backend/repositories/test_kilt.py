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
    assert hits[0].score > hits[1].score > 0
    assert hits[0].paragraph("kilt", 2).paragraph_ref == "kilt:internal-id:2"
    client.search.assert_awaited_once()
    assert client.search.call_args.kwargs["source"] == [
        "wikipedia_title",
        "wikipedia_id",
        "text",
        "anchors",
    ]
    client.get.assert_not_awaited()


async def test_search_preserves_stopword_only_titles_with_fallback():
    client = AsyncMock()
    client.search.side_effect = [
        {"hits": {"hits": []}},
        {
            "hits": {
                "hits": [
                    {
                        "_id": "42",
                        "_score": 1.0,
                        "_source": {
                            "wikipedia_title": "To Be or Not to Be",
                            "text": ["A comedy film."],
                        },
                    }
                ]
            }
        },
    ]
    hits = await ElasticsearchKiltRepository(client).asearch("to be or not to be", 5)
    assert [hit.title for hit in hits] == ["To Be or Not to Be"]
    assert hits[0].paragraphs == ("A comedy film.",)
    assert client.search.await_count == 2
    fallback = client.search.call_args.kwargs
    assert "analyzer" not in fallback["query"]["multi_match"]
    assert fallback["size"] == 100


async def test_search_returns_empty_when_fallback_also_has_no_matches():
    client = AsyncMock()
    client.search.return_value = {"hits": {"hits": []}}
    assert await ElasticsearchKiltRepository(client).asearch("absent") == []
    assert client.search.await_count == 2


async def test_search_expands_linked_articles_and_preserves_original_paragraphs():
    client = AsyncMock()
    original = {
        "_id": "1",
        "_score": 3.0,
        "_source": {
            "wikipedia_id": "1",
            "wikipedia_title": "Painter",
            "text": ["Painter artworks are displayed at City House."],
            "anchors": [
                {"paragraph_id": 0, "href": "City_House#Collection"},
            ],
        },
    }
    related = {
        "_id": "2",
        "_score": 2.0,
        "_source": {
            "wikipedia_title": "City House",
            "text": ["Section::::Art.", "Original painter artworks."],
        },
    }
    client.search.side_effect = [
        {"hits": {"hits": [original]}},
        {"hits": {"hits": [original, related]}},
    ]
    hits = await ElasticsearchKiltRepository(client).asearch("painter artworks", 10)
    assert {hit.wikipedia_id for hit in hits} == {"1", "2"}
    assert len(hits) == 2
    linked = next(hit for hit in hits if hit.wikipedia_id == "2")
    assert linked.paragraphs == ("Section::::Art.", "Original painter artworks.")
    assert linked.paragraph("kilt", 1).paragraph_ref == "kilt:2:1"
    assert client.search.call_args.kwargs["query"]["bool"]["filter"] == [
        {"terms": {"wikipedia_title.keyword": ["City House"]}}
    ]
    client.get.assert_not_awaited()


async def test_search_uses_same_candidate_pool_for_different_output_limits():
    client = AsyncMock()
    client.search.return_value = {
        "hits": {
            "hits": [
                {
                    "_id": str(i),
                    "_source": {"wikipedia_title": str(i), "text": ["fox habitat"]},
                }
                for i in range(15)
            ]
        }
    }
    repo = ElasticsearchKiltRepository(client)
    one = await repo.asearch("fox habitat", 1)
    ten = await repo.asearch("fox habitat", 10)
    assert len(one) == 1
    assert len(ten) == 10
    assert one[0].id == ten[0].id
    assert all(call.kwargs["size"] == 100 for call in client.search.call_args_list)
