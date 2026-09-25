"""Standalone interview exercise: implementation and tests in one file.

Requires pytest.
Run directly: python highlight_sources.py
Run with pytest: python -m pytest highlight_sources.py -v
"""

import pytest


def highlight_sources(text: str, sources: list[str]) -> dict:
    """Highlight the union of matching spans and count overlapping matches.

    Adjacent spans merge too. Empty sources have zero matches. Region offsets
    refer to the original text, with an exclusive end index.

    """
    # Deduplicate sources while preserving their input order.
    source_order = {source: i for i, source in enumerate(dict.fromkeys(sources))}
    counts = {}
    matches = []

    for source in source_order:
        counts[source] = 0
        if not source:
            continue

        start = text.find(source)
        while start != -1:
            counts[source] += 1
            matches.append((start, start + len(source), source))
            # Advance by one so overlapping occurrences count.
            start = text.find(source, start + 1)

    matches.sort(key=lambda match: (match[0], match[1]))

    # Each region is [start, end, set_of_contributors].
    merged = []
    for start, end, source in matches:
        if not merged or start > merged[-1][1]:
            merged.append([start, end, {source}])
        else:
            merged[-1][1] = max(merged[-1][1], end)
            merged[-1][2].add(source)

    parts = []
    regions = []
    cursor = 0

    for start, end, contributors in merged:
        parts.extend(
            [
                text[cursor:start],
                "<yellow>",
                text[start:end],
                "</yellow>",
            ]
        )
        regions.append(
            (
                start,
                end,
                sorted(contributors, key=source_order.__getitem__),
            )
        )
        cursor = end

    parts.append(text[cursor:])

    return {
        "highlighted": "".join(parts),
        # Counts align with the original input, including duplicate sources.
        "counts": [counts[source] for source in sources],
        "regions": regions,
    }


@pytest.mark.parametrize(
    "case_id, text, sources, expected",
    [
        (
            "separate-matches",
            "cat and cat!",
            ["cat", "dog"],
            {
                "highlighted": "<yellow>cat</yellow> and <yellow>cat</yellow>!",
                "counts": [2, 0],
                "regions": [(0, 3, ["cat"]), (8, 11, ["cat"])],
            },
        ),
        (
            "overlapping-occurrences",
            "banana",
            ["ana"],
            {
                "highlighted": "b<yellow>anana</yellow>",
                "counts": [2],
                "regions": [(1, 6, ["ana"])],
            },
        ),
        (
            "duplicates-and-contributor-order",
            "abcde",
            ["cde", "abc", "cde", "bc"],
            {
                "highlighted": "<yellow>abcde</yellow>",
                "counts": [1, 1, 1, 1],
                "regions": [(0, 5, ["cde", "abc", "bc"])],
            },
        ),
        (
            "adjacent-matches",
            "abcd",
            ["ab", "cd"],
            {
                "highlighted": "<yellow>abcd</yellow>",
                "counts": [1, 1],
                "regions": [(0, 4, ["ab", "cd"])],
            },
        ),
        (
            "empty-sources-and-no-matches",
            "abc",
            ["", "xyz", ""],
            {"highlighted": "abc", "counts": [0, 0, 0], "regions": []},
        ),
        (
            "empty-text",
            "",
            ["a", ""],
            {"highlighted": "", "counts": [0, 0], "regions": []},
        ),
        (
            "no-sources",
            "abc",
            [],
            {"highlighted": "abc", "counts": [], "regions": []},
        ),
    ],
)
def test_highlight_sources(case_id, text, sources, expected):
    assert highlight_sources(text, sources) == expected, case_id


if __name__ == "__main__":
    # Passing the filename explicitly collects tests in this standalone file.
    raise SystemExit(pytest.main([__file__, "-v"]))
