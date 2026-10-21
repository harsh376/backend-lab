"""Build and verify the KILT v1 evaluation dataset."""

import argparse
import asyncio
import hashlib
import json
import random
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

from elastic_transport import TransportError
from elasticsearch import ApiError, AsyncElasticsearch
from pydantic import ValidationError

# Support direct execution by file path from an uninstalled checkout.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from apps.evals.dataset import load_cases  # noqa: E402
from apps.evals.models import EvalCase, Evidence, VerificationTag  # noqa: E402
from backend.config import Settings  # noqa: E402


def build_cases(
    sources: list[tuple[str, Path, int]], seed: int
) -> tuple[list[dict], list[dict]]:
    cases = []
    source_metadata = []
    seen_questions: set[str] = set()
    seen_ids: set[str] = set()
    for dataset, path, count in sources:
        raw = path.read_bytes()
        records = []
        for number, line in enumerate(raw.splitlines(), 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                if not isinstance(record, dict):
                    raise ValueError("record must be an object")
                records.append(record)
            except ValueError as error:
                raise ValueError(f"{path}:{number}: {error}") from error
        eligible = []
        for record in records:
            question = record.get("input")
            outputs = record.get("output")
            if not isinstance(question, str) or not question.strip():
                continue
            if record.get("id") is None or not isinstance(outputs, list):
                continue
            answers = list(
                dict.fromkeys(
                    output["answer"]
                    for output in outputs
                    if isinstance(output, dict)
                    and isinstance(output.get("answer"), str)
                    and output["answer"].strip()
                )
            )
            evidence_sets = []
            seen_sets = set()
            for output in outputs:
                if not isinstance(output, dict):
                    continue
                provenance = output.get("provenance")
                if not isinstance(provenance, list) or not provenance:
                    continue
                try:
                    for evidence in provenance:
                        Evidence.model_validate(evidence)
                except ValidationError:
                    continue
                key = json.dumps(provenance, sort_keys=True)
                if key not in seen_sets:
                    seen_sets.add(key)
                    evidence_sets.append(provenance)
            if answers and evidence_sets:
                eligible.append((record, answers, evidence_sets))
        # Independent RNG per source preserves the original pilot selection.
        random.Random(seed).shuffle(eligible)
        selected = 0
        for record, answers, evidence_sets in eligible:
            if selected == count:
                break
            normalized = re.sub(r"\W+", " ", record["input"].casefold()).strip()
            case_id = f"{dataset}-dev-{record['id']}"
            if normalized in seen_questions or case_id in seen_ids:
                continue
            seen_questions.add(normalized)
            seen_ids.add(case_id)
            case = {
                "case_id": case_id,
                "group_id": "question-"
                + hashlib.sha256(normalized.encode()).hexdigest()[:16],
                "question": record["input"],
                "source": {
                    "dataset": dataset,
                    "split": "dev",
                    "record_id": str(record["id"]),
                    "filename": path.name,
                    "original_output": record["output"],
                },
                "accepted_answers": answers,
                "answerable": True,
                "evidence_sets": evidence_sets,
                "tags": ["open_domain_qa", dataset]
                + (["multi_evidence"] if dataset == "hotpotqa" else []),
            }
            EvalCase.model_validate(case)
            cases.append(case)
            selected += 1
        if selected != count:
            raise ValueError(
                f"{path}: requested {count} cases, "
                f"only {selected} unique eligible cases"
            )
        source_metadata.append(
            {
                "dataset": dataset,
                "split": "dev",
                "filename": path.name,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "source_record_count": len(records),
                "eligible_record_count": len(eligible),
                "selected_count": selected,
            }
        )
    return cases, source_metadata


def nonnegative(value: str) -> int:
    count = int(value)
    if count < 0:
        raise argparse.ArgumentTypeError("count must be nonnegative")
    return count


def identify_corpus(path: Path) -> dict:
    """Identify the supplied KILT artifact with bounded memory usage."""
    path = path.expanduser()
    print(f"Hashing corpus file: {path}", flush=True)
    with path.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    return {
        "name": "kilt_knowledgesource",
        "wikipedia_dump_date": "2019-08-01",
        "filename": path.name,
        "sha256": digest,
    }


def build_dataset(args) -> Path:
    destination = args.output_dir / "dev.json"
    manifest_path = args.output_dir / "manifest.json"
    if destination.exists() and not args.overwrite:
        raise ValueError(f"{destination} exists; use --overwrite to replace it")
    if args.nq_count + args.hotpotqa_count == 0:
        raise ValueError("request at least one case")
    cases, sources = build_cases(
        [
            ("nq", args.nq.expanduser(), args.nq_count),
            ("hotpotqa", args.hotpotqa.expanduser(), args.hotpotqa_count),
        ],
        args.seed,
    )
    manifest = (
        json.loads(manifest_path.read_text())
        if manifest_path.exists()
        else {
            "dataset_version": args.output_dir.name,
            "schema_version": 1,
            "corpus_snapshot": None,
            "files": {},
            "case_counts": {},
        }
    )
    if args.corpus_file is not None:
        manifest["corpus_snapshot"] = identify_corpus(args.corpus_file)
    manifest["status"] = "dev_populated_pending_review"
    manifest.setdefault("files", {})["dev"] = "dev.json"
    manifest.setdefault("case_counts", {})["dev"] = len(cases)
    manifest["split_seed"] = args.seed
    manifest["split_group_key"] = "group_id"
    manifest["sampling"] = {
        "seed": args.seed,
        "method": "shuffle eligible records independently per source; "
        "take first unique normalized questions",
        "eligibility": "Nonempty question and answers; "
        "at least one structurally valid provenance set",
        "sources": sources,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(cases, ensure_ascii=False, indent=2) + "\n")
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Wrote {len(cases)} cases to {destination}")
    return destination


def inspect_evidence(evidence: Evidence, hits: list[dict]) -> dict:
    """Check bounds in original stored paragraphs; retain text for inspection."""
    result = {
        "wikipedia_id": evidence.wikipedia_id,
        "errors": [],
        "passages": [],
        "page_verified": False,
    }
    errors = result["errors"]
    if len(hits) != 1:
        errors.append("article_missing" if not hits else "ambiguous_wikipedia_id")
        return result
    result["page_verified"] = True
    hit = hits[0]
    result["article_id"] = hit["_id"]
    source = hit["_source"]
    result["title"] = source.get("wikipedia_title")
    paragraphs = source.get("text")
    if not isinstance(paragraphs, list) or not all(
        isinstance(paragraph, str) for paragraph in paragraphs
    ):
        errors.append("invalid_article_text")
        return result
    start, end = evidence.start_paragraph_id, evidence.end_paragraph_id
    if end >= len(paragraphs):
        errors.append("paragraph_out_of_bounds")
        return result
    result["passages"] = [
        {"paragraph_id": i, "text": paragraphs[i]} for i in range(start, end + 1)
    ]
    if not any(paragraphs[i].strip() for i in range(start, end + 1)):
        errors.append("empty_evidence")
    extra = evidence.model_extra or {}
    for key, paragraph_id in (("start_character", start), ("end_character", end)):
        if key in extra:
            offset = extra[key]
            if type(offset) is not int or not 0 <= offset <= len(
                paragraphs[paragraph_id]
            ):
                errors.append(f"invalid_{key}")
    if (
        start == end
        and type(extra.get("start_character")) is int
        and type(extra.get("end_character")) is int
        and extra["start_character"] >= extra["end_character"]
    ):
        errors.append("empty_or_reversed_character_span")
    return result


async def verify_cases(
    client: AsyncElasticsearch, index: str, cases: list[EvalCase]
) -> list[dict]:
    cache = {}
    results = []
    for case in cases:
        sets = []
        for evidence_set in case.evidence_sets:
            checks = []
            for evidence in evidence_set:
                wiki_id = evidence.wikipedia_id
                if wiki_id not in cache:
                    response = await client.search(
                        index=index,
                        query={"term": {"wikipedia_id": wiki_id}},
                        size=2,
                        source=["wikipedia_title", "text"],
                    )
                    cache[wiki_id] = response["hits"]["hits"]
                checks.append(inspect_evidence(evidence, cache[wiki_id]))
            sets.append(checks)
        # Conservative case tags allow evaluators to use all declared alternatives.
        # Valid alternative indices also permit explicitly filtered evaluation.
        page_verified = bool(sets) and all(
            check["page_verified"] for checks in sets for check in checks
        )
        passage_verified = bool(sets) and all(
            not check["errors"] for checks in sets for check in checks
        )
        tags = []
        if case.answerable and page_verified:
            tags.append(VerificationTag.PAGE_VERIFIED)
        if case.answerable and passage_verified:
            tags.append(VerificationTag.PASSAGE_VERIFIED)
        results.append(
            {
                "case_id": case.case_id,
                "question": case.question,
                "accepted_answers": case.accepted_answers,
                "verification_tags": tags,
                "valid_passage_evidence_set_indices": [
                    i
                    for i, checks in enumerate(sets)
                    if all(not check["errors"] for check in checks)
                ],
                "passed": passage_verified and case.answerable,
                "reason": (
                    "unanswerability_requires_separate_review"
                    if not case.answerable
                    else "references_valid"
                    if passage_verified
                    else "invalid_references"
                ),
                "evidence_sets": sets,
            }
        )
    return results


async def verify_dataset(args) -> int:
    original = args.dataset.read_bytes()
    cases = load_cases(args.dataset)
    async with AsyncElasticsearch(args.elasticsearch_url) as client:
        # Record concrete index UUIDs; an alias/index name is not a snapshot hash.
        indices = await client.indices.get_settings(index=args.index)
        results = await verify_cases(client, args.index, cases)
    report = {
        "checked_at": datetime.now(UTC).isoformat(),
        "dataset": str(args.dataset),
        "dataset_sha256": hashlib.sha256(original).hexdigest(),
        "index": args.index,
        "index_uuids": {
            name: info["settings"]["index"]["uuid"] for name, info in indices.items()
        },
        "scope": "Structural provenance checks; source labels are trusted. "
        "Does not establish semantic support or snapshot immutability.",
        "total": len(results),
        "page_verified": sum(
            VerificationTag.PAGE_VERIFIED in result["verification_tags"]
            for result in results
        ),
        "passage_verified": sum(result["passed"] for result in results),
        "cases": results,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    if args.write:
        # Replace only verifier-owned tags, retaining task and rejection labels.
        records = json.loads(original)
        for record, result in zip(records, results, strict=True):
            record["tags"] = [
                tag for tag in record.get("tags", []) if tag not in VerificationTag
            ] + result["verification_tags"]
        if args.dataset.read_bytes() != original:
            raise ValueError(
                "Dataset changed during verification; refusing to overwrite"
            )
        args.dataset.write_text(
            json.dumps(records, ensure_ascii=False, indent=2) + "\n"
        )
    print(
        f"{report['page_verified']}/{len(results)} page-verified; "
        f"{report['passage_verified']}/{len(results)} passage-verified; "
        f"report: {args.report}"
    )
    return 0 if report["passage_verified"] == len(results) else 1


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="Curate raw dev JSONL into dev.json")
    build.add_argument("--nq", required=True, type=Path)
    build.add_argument("--hotpotqa", required=True, type=Path)
    build.add_argument("--nq-count", type=nonnegative, default=30)
    build.add_argument("--hotpotqa-count", type=nonnegative, default=15)
    build.add_argument("--seed", type=int, default=42)
    build.add_argument(
        "--corpus-file",
        type=Path,
        help="Hash the imported KILT knowledge-source file into corpus_snapshot",
    )
    build.add_argument(
        "--output-dir", type=Path, default=Path(__file__).resolve().parent
    )
    build.add_argument("--overwrite", action="store_true")
    build.add_argument(
        "--verify",
        action="store_true",
        help="Verify the built dataset and write verification tags",
    )
    verify = commands.add_parser(
        "verify", help="Check provenance against Elasticsearch"
    )
    verify.add_argument(
        "--dataset", type=Path, default=Path(__file__).resolve().with_name("dev.json")
    )
    verify.add_argument(
        "--write",
        action="store_true",
        help="Refresh verification tags; other tags are preserved",
    )
    settings = Settings()
    for command in (build, verify):
        command.add_argument("--elasticsearch-url", default=settings.elasticsearch_url)
        command.add_argument("--index", default=settings.kilt_index)
        command.add_argument(
            "--report",
            type=Path,
            default=(
                Path(__file__).resolve().parents[2]
                / "runs"
                / "kilt-v1-verification.json"
            ),
        )
    return parser


def main() -> None:
    parser = make_parser()
    args = parser.parse_args()
    try:
        if args.command == "build":
            args.dataset = build_dataset(args)
            if not args.verify:
                return
            args.write = True
        code = asyncio.run(verify_dataset(args))
    except (OSError, ValueError, ApiError, TransportError) as error:
        parser.error(str(error))
    raise SystemExit(code)


if __name__ == "__main__":
    main()
