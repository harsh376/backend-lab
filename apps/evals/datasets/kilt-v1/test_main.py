"""Test KILT dataset verification and CLI routing without Elasticsearch."""

import hashlib
import importlib.util
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from apps.evals.dataset import load_cases
from apps.evals.models import Evidence

spec = importlib.util.spec_from_file_location(
    "kilt_verify", Path(__file__).with_name("main.py")
)
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)


def evidence(**extra):
    return Evidence(
        wikipedia_id="42", start_paragraph_id=0, end_paragraph_id=0, **extra
    )


@pytest.mark.parametrize(
    "hits,expected",
    [([], "article_missing"), ([{}, {}], "ambiguous_wikipedia_id")],
)
def test_missing_or_ambiguous_article(hits, expected):
    assert verify.inspect_evidence(evidence(), hits)["errors"] == [expected]


@pytest.mark.parametrize(
    "paragraphs,extra,expected",
    [
        ([], {}, "paragraph_out_of_bounds"),
        ([""], {}, "empty_evidence"),
        (["abc"], {"end_character": 4}, "invalid_end_character"),
        (["abc"], {"start_character": -1}, "invalid_start_character"),
        (
            ["abc"],
            {"start_character": 2, "end_character": 1},
            "empty_or_reversed_character_span",
        ),
    ],
)
def test_bad_bounds(paragraphs, extra, expected):
    hit = {"_id": "different-from-wikipedia-id", "_source": {"text": paragraphs}}
    assert expected in verify.inspect_evidence(evidence(**extra), [hit])["errors"]


def test_valid_exclusive_end_offset():
    hit = {"_id": "doc", "_source": {"text": ["abc"]}}
    result = verify.inspect_evidence(
        evidence(start_character=0, end_character=3), [hit]
    )
    assert not result["errors"]
    assert result["passages"] == [{"paragraph_id": 0, "text": "abc"}]


async def test_query_uses_wikipedia_id_and_caches_repeated_references():
    case = load_cases(Path(__file__).with_name("dev.json"))[0]
    case.evidence_sets = [[evidence(), evidence()]]
    client = AsyncMock()
    client.search.return_value = {
        "hits": {"hits": [{"_id": "other-id", "_source": {"text": ["abc"]}}]}
    }
    results = await verify.verify_cases(client, "kilt", [case])
    assert results[0]["passed"]
    assert results[0]["verification_tags"] == ["page_verified", "passage_verified"]
    client.search.assert_awaited_once_with(
        index="kilt",
        query={"term": {"wikipedia_id": "42"}},
        size=2,
        source=["wikipedia_title", "text"],
    )


async def test_empty_span_preserves_page_eligibility():
    case = load_cases(Path(__file__).with_name("dev.json"))[0]
    case.evidence_sets = [
        [evidence(start_character=0, end_character=0)],
        [evidence(start_character=0, end_character=3)],
    ]
    client = AsyncMock()
    client.search.return_value = {
        "hits": {"hits": [{"_id": "doc", "_source": {"text": ["abc"]}}]}
    }
    result = (await verify.verify_cases(client, "kilt", [case]))[0]
    assert result["verification_tags"] == ["page_verified"]
    assert result["valid_passage_evidence_set_indices"] == [1]
    assert not result["passed"]


async def test_missing_page_has_no_verification_tags():
    case = load_cases(Path(__file__).with_name("dev.json"))[0]
    client = AsyncMock()
    client.search.return_value = {"hits": {"hits": []}}
    result = (await verify.verify_cases(client, "kilt", [case]))[0]
    assert not result["verification_tags"]
    assert not result["valid_passage_evidence_set_indices"]


def test_build_command_can_chain_verification(monkeypatch, tmp_path):
    dataset = tmp_path / "dev.json"
    built = []

    def build(args):
        built.append(args)
        return dataset

    check = AsyncMock(return_value=0)
    monkeypatch.setattr(verify, "build_dataset", build)
    monkeypatch.setattr(verify, "verify_dataset", check)
    monkeypatch.setattr(
        "sys.argv",
        [
            "main.py",
            "build",
            "--nq",
            "nq.jsonl",
            "--hotpotqa",
            "hotpot.jsonl",
            "--verify",
        ],
    )
    with pytest.raises(SystemExit) as result:
        verify.main()
    assert result.value.code == 0
    assert built[0].dataset == dataset
    assert built[0].write is True
    check.assert_awaited_once_with(built[0])


def test_build_without_verify_is_offline(monkeypatch, tmp_path):
    check = AsyncMock()
    monkeypatch.setattr(verify, "build_dataset", lambda args: tmp_path / "dev.json")
    monkeypatch.setattr(verify, "verify_dataset", check)
    monkeypatch.setattr(
        "sys.argv",
        [
            "main.py",
            "build",
            "--nq",
            "nq.jsonl",
            "--hotpotqa",
            "hotpot.jsonl",
        ],
    )
    verify.main()
    check.assert_not_awaited()


def test_verify_defaults_to_report_only():
    args = verify.make_parser().parse_args(["verify"])
    assert args.write is False
    assert args.dataset.name == "dev.json"


def test_build_records_corpus_identity_and_preserves_it_on_rebuild(
    monkeypatch, tmp_path
):
    corpus = tmp_path / "corpus.json"
    content = b'{"wikipedia_id": "42", "text": ["Evidence"]}\n'
    corpus.write_bytes(content)
    monkeypatch.setattr(verify, "build_cases", lambda sources, seed: ([], []))
    output = tmp_path / "dataset"
    args = verify.make_parser().parse_args(
        [
            "build",
            "--nq",
            "nq.jsonl",
            "--hotpotqa",
            "hotpotqa.jsonl",
            "--output-dir",
            str(output),
            "--corpus-file",
            str(corpus),
        ]
    )
    verify.build_dataset(args)
    manifest_path = output / "manifest.json"
    snapshot = json.loads(manifest_path.read_text())["corpus_snapshot"]
    assert snapshot == {
        "name": "kilt_knowledgesource",
        "wikipedia_dump_date": "2019-08-01",
        "filename": "corpus.json",
        "sha256": hashlib.sha256(content).hexdigest(),
    }
    args.corpus_file = None
    args.overwrite = True
    verify.build_dataset(args)
    assert json.loads(manifest_path.read_text())["corpus_snapshot"] == snapshot


def test_missing_corpus_does_not_overwrite_dataset(monkeypatch, tmp_path):
    monkeypatch.setattr(verify, "build_cases", lambda sources, seed: ([], []))
    dataset = tmp_path / "dev.json"
    dataset.write_text("existing dataset")
    args = verify.make_parser().parse_args(
        [
            "build",
            "--nq",
            "nq.jsonl",
            "--hotpotqa",
            "hotpotqa.jsonl",
            "--output-dir",
            str(tmp_path),
            "--corpus-file",
            str(tmp_path / "missing"),
            "--overwrite",
        ]
    )
    with pytest.raises(FileNotFoundError):
        verify.build_dataset(args)
    assert dataset.read_text() == "existing dataset"
