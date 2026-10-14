"""KILT corpus records and structural metadata."""

import re

from backend.domains.base import DomainModel

CATEGORY_SEPARATOR = re.compile(r",(?! )")
SECTION_MARKER = "Section::::"
SECTION_PATH_SEPARATOR = ".:"


class KiltPassage(DomainModel):
    passage_id: str
    corpus_version: str
    wikipedia_id: str
    paragraph_id: int
    title: str
    text: str


class KiltArticle(DomainModel):
    id: str
    wikipedia_id: str
    title: str
    paragraphs: tuple[str, ...]

    def passage(self, corpus_version: str, paragraph_id: int) -> KiltPassage:
        if paragraph_id < 0:
            raise ValueError("paragraph_id must be non-negative")
        if paragraph_id >= len(self.paragraphs):
            raise ValueError("paragraph_id is out of range")
        return KiltPassage(
            passage_id=f"{corpus_version}:{self.id}:{paragraph_id}",
            corpus_version=corpus_version,
            wikipedia_id=self.wikipedia_id,
            paragraph_id=paragraph_id,
            title=self.title,
            text=self.paragraphs[paragraph_id],
        )


class KiltSearchHit(DomainModel):
    id: str
    title: str
    score: float | None
    snippets: tuple[str, ...] = ()


def split_categories(categories: str) -> list[str]:
    parts = (part.strip() for part in CATEGORY_SEPARATOR.split(categories))
    return [part for part in parts if part]


def extract_sections(paragraphs: list[str]) -> list[str]:
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
