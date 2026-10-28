"""Model-free article expansion and passage ranking over a bounded candidate pool."""

import math
import re
import unicodedata
from collections import Counter
from urllib.parse import unquote

CANDIDATE_LIMIT = 100
SEED_LIMIT = 3
PARAGRAPH_LIMIT = 5
LINK_LIMIT = 100
PASSAGE_SIZE = 120
PASSAGE_STRIDE = 80
RRF_CONSTANT = 10

# Keep content words such as "most" while dropping question framing. This is
# used only for local scoring; the Elasticsearch query keeps its own analyzer.
STOP_WORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "but",
        "by",
        "for",
        "if",
        "in",
        "into",
        "is",
        "it",
        "no",
        "not",
        "of",
        "on",
        "or",
        "such",
        "that",
        "the",
        "their",
        "then",
        "there",
        "these",
        "they",
        "this",
        "to",
        "was",
        "will",
        "with",
        "who",
        "what",
        "when",
        "where",
        "which",
        "how",
        "did",
        "does",
        "do",
        "whose",
        "whom",
        "has",
        "have",
        "had",
        "can",
        "could",
        "would",
        "should",
        "much",
        "many",
    ]
)


def words(text: str) -> list[str]:
    normalized = "".join(
        char
        for char in unicodedata.normalize("NFKD", text.casefold())
        if not unicodedata.combining(char)
    )
    return [word for word in re.findall(r"\w+", normalized) if word not in STOP_WORDS]


def page_id(hit: dict) -> str:
    return str(hit["_source"].get("wikipedia_id", hit["_id"]))


def related_titles(query: str, hits: list[dict]) -> list[str]:
    """Collect links from the most relevant paragraphs of the first three hits."""
    terms = set(words(query))
    titles: Counter[str] = Counter()
    for seed_rank, hit in enumerate(hits[:SEED_LIMIT], start=1):
        source = hit["_source"]
        paragraphs = []
        for index, paragraph in enumerate(source.get("text", [])):
            tokens = set(words(paragraph))
            # Prefer focused paragraphs over long paragraphs with incidental
            # matches. Seed rank limits the influence of less reliable articles.
            relevance = len(terms & tokens) / (1 + len(tokens) ** 0.3)
            paragraphs.append((relevance, index))
        selected = {
            index: relevance
            for relevance, index in sorted(paragraphs, reverse=True)[:PARAGRAPH_LIMIT]
            if relevance > 0
        }
        for anchor in source.get("anchors", []):
            paragraph_id = anchor.get("paragraph_id")
            if paragraph_id not in selected:
                continue
            title = unquote(anchor.get("href", "")).split("#", 1)[0].replace("_", " ")
            if title and not title.startswith(("wikt:", "File:", "Category:")):
                titles[title] += selected[paragraph_id] / seed_rank
    return [title for title, _ in titles.most_common(LINK_LIMIT)]


def rank_passages(query: str, hits: list[dict]) -> list[str]:
    """Rank articles by their strongest overlapping passage, using local BM25.

    Statistics come from candidate passages, never evaluation references. Titles
    provide context to every passage. Original article paragraphs remain intact.
    """
    terms = set(words(query))
    passages = []
    frequencies: Counter[str] = Counter()
    for rank, hit in enumerate(hits):
        source = hit["_source"]
        title = words(source["wikipedia_title"]) * 3
        for paragraph in source.get("text", []):
            tokens = words(paragraph)
            for start in range(0, len(tokens), PASSAGE_STRIDE):
                window = tokens[start : start + PASSAGE_SIZE] + title
                counts = Counter(word for word in window if word in terms)
                passages.append((rank, counts, len(window)))
                frequencies.update(counts.keys())
    count = len(passages)
    average_length = sum(length for _, _, length in passages) / max(count, 1)
    idf = {
        term: math.log(
            1 + (count - frequencies[term] + 0.5) / (frequencies[term] + 0.5)
        )
        for term in terms
    }
    scores = dict.fromkeys(range(len(hits)), 0.0)
    for rank, counts, length in passages:
        score = sum(
            idf[term]
            * frequency
            * 2.2
            / (frequency + 1.2 * (0.25 + 0.75 * length / max(average_length, 1)))
            for term, frequency in counts.items()
        )
        scores[rank] = max(scores[rank], score)
    return [
        page_id(hits[rank]) for rank in sorted(scores, key=scores.get, reverse=True)
    ]


def fuse_rankings(rankings: list[list[str]]) -> list[tuple[str, float]]:
    """Reciprocal rank fusion; score scales need not match between retrievers."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, article_id in enumerate(dict.fromkeys(ranking), start=1):
            scores[article_id] = scores.get(article_id, 0.0) + 1 / (RRF_CONSTANT + rank)
    return sorted(scores.items(), key=lambda item: item[1], reverse=True)
