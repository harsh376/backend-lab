from copy import deepcopy

import pytest

from backend.repositories.kilt_ranking import (
    fuse_rankings,
    rank_passages,
    related_titles,
    words,
)


def hit(article_id, text, title="Article", anchors=()):
    return {
        "_id": article_id,
        "_source": {"wikipedia_title": title, "text": text, "anchors": list(anchors)},
    }


def test_local_words_fold_accents_and_remove_question_framing():
    assert words("Where is Gualeguaychú?") == ["gualeguaychu"]


def test_expansion_uses_relevant_paragraphs_and_decodes_link_titles():
    source = hit(
        "1",
        ["Painter artworks are displayed at City House.", "Unrelated sports teams."],
        anchors=[
            {"paragraph_id": 0, "href": "City_House#Art"},
            {"paragraph_id": 0, "href": "Mus%C3%A9e"},
            {"paragraph_id": 0, "href": "Category:Art"},
            {"paragraph_id": 1, "href": "Sports"},
        ],
    )
    assert related_titles("painter artworks", [source]) == ["City House", "Musée"]


def test_expansion_bounds_seed_count_and_number_of_links():
    seeds = [hit(str(i), ["other"]) for i in range(3)]
    seeds.append(hit("4", ["fox"], anchors=[{"paragraph_id": 0, "href": "Ignored"}]))
    assert related_titles("fox", seeds) == []
    seed = hit(
        "1", ["fox"], anchors=[{"paragraph_id": 0, "href": str(i)} for i in range(150)]
    )
    assert len(related_titles("fox", [seed])) == 100


def test_passage_ranking_finds_focused_evidence_in_a_long_article_without_mutation():
    hits = [
        hit("noise", ["red", "fox", "habitat"]),
        hit("evidence", ["unrelated " * 1000, "red fox habitat"]),
    ]
    before = deepcopy(hits)
    assert rank_passages("red fox habitat", hits)[0] == "evidence"
    assert hits == before


def test_empty_and_stopword_only_passages_have_stable_order():
    hits = [hit("1", []), hit("2", ["the and"])]
    assert rank_passages("the and", hits) == ["1", "2"]
    assert rank_passages("fox", []) == []


def test_fusion_deduplicates_each_ranking_and_is_stable_for_ties():
    result = fuse_rankings([["a", "a", "b"], ["b", "a"]])
    assert [article_id for article_id, _ in result] == ["a", "b"]
    assert result[0][1] == pytest.approx(1 / 11 + 1 / 12)
    assert result[0][1] == result[1][1]
    assert fuse_rankings([]) == []
