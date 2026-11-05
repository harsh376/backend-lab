# KILT v1 dataset

Run commands from the repository root. The bundled `dev.json` contains
45 cases (30 NQ and 15 HotpotQA); `manifest.json` records source hashes,
sampling settings, counts, and corpus source identity.

Corpus verification has already been run and its tags are saved in `dev.json`:

- 45/45 cases have `page_verified`.
- 33/45 cases have `passage_verified` (the tag for paragraph-range and character-offset checks).

The verification tags record structural corpus checks only. Answer correctness
and semantic support are recorded per case in `review` (see [Review](#review)).
Refresh corpus verification when the dataset or corpus changes.

## Build

Select 30 NQ and 15 HotpotQA cases with seed 42; write `dev.json` and `manifest.json`:

```sh
uv run python apps/evals/datasets/kilt-v1/main.py build \
  --nq ~/Desktop/nq-dev-kilt.jsonl \
  --hotpotqa ~/Desktop/hotpotqa-dev-kilt.jsonl \
  --nq-count 30 --hotpotqa-count 15 --seed 42
```

Add `--overwrite` to replace existing cases, `--verify` to also verify and write
verification tags, or `--output-dir /tmp/kilt-v1` to build a separate copy.

Record the corpus source identity during build by also passing:

```sh
--corpus-file ~/Desktop/kilt_knowledgesource.json
```

This streams SHA-256 into `manifest.json` under `corpus_snapshot`; hashing the
large file may take minutes. Supply the file used for ingestion. This records
source identity, not Elasticsearch completeness. Without the flag, an existing
snapshot entry is preserved; new manifests use `null`.

## Verify

Verification requires Elasticsearch populated with the KILT corpus. Defaults
come from `ELASTICSEARCH_URL` and `KILT_INDEX` (host defaults:
`http://localhost:9200` and `kilt`).

Report only:

```sh
uv run python apps/evals/datasets/kilt-v1/main.py verify
```

Refresh verification tags in `dev.json`:

```sh
uv run python apps/evals/datasets/kilt-v1/main.py verify --write
```

Override the Elasticsearch target:

```sh
uv run python apps/evals/datasets/kilt-v1/main.py verify \
  --elasticsearch-url http://localhost:9200 --index kilt --write
```

Report: `apps/evals/runs/kilt-v1-verification.json` (override with `--report`).
The report includes dataset SHA-256, concrete Elasticsearch index UUIDs,
per-evidence checks, and valid evidence-set indices. It does not freeze the index.

- `page_verified`: all referenced pages resolve uniquely.
- `passage_verified`: all referenced paragraph ranges and supplied character offsets pass.

Checks trust source labels; they do not prove semantic support. Other tags are
preserved. Rebuilding clears verification tags.

Exit codes: `0` all cases are answerable and pass passage checks; `1` some do
not; `2` command or service error. Unanswerable cases require separate review.

## Review

Every case carries a `review` with its decision, reason, and date, checked
against the case's evidence and the 2019 corpus snapshot. Decisions are applied
in `dev.json` itself; `source.original_output` keeps the original gold, so each
amendment can be compared with the source.

- `keep`: gold is correct as built; may add tags.
- `amend`: accepted answers or evidence were changed; the reason says how.
- `reject`: the case also carries the `rejected` tag, which evaluation always
  excludes. Validation requires the decision and the tag to agree.

Policy: gold is aligned with the corpus snapshot, not with today. A question
whose answer depends on "now" keeps the corpus answer and is tagged
`time_sensitive`. Other review tags: `ambiguous` (more than one reasonable
reading, or corpus-supported answers outside the gold) and `list_answer` (the
question asks for several items; single-item alternatives were removed).

Review of 2026-11-04: 32 keep, 9 amend, 4 reject (none passage-verified), so 41
cases are eligible and 33 remain `passage_verified` (re-verified after the
amendments). `build --overwrite` refuses to replace reviewed cases unless
`--discard-reviews` is also passed; a rebuilt dataset needs a new review.

## Case format and selection

Each case has `case_id`, `group_id`, `question`, `source`, `accepted_answers`,
`answerable`, `evidence_sets`, `tags`, and an optional `review`. Source metadata retains the dataset,
split, record ID, filename, and original output. Each evidence set is an
alternative complete set of passages, identified by Wikipedia ID and inclusive
paragraph range; evidence may also retain source character offsets.

The builder samples eligible records deterministically with the selected seed
and avoids duplicate normalized questions across sources. Schema validation
requires answerable cases to have a nonblank accepted answer. Evidence sets are
optional for correctness scoring; any supplied set must be nonempty. The KILT
builder selects cases with gold evidence, independently of the shared contract.
Schema validation does not establish semantic support or split isolation.

Evaluation excludes cases tagged `rejected`. `--tags` requires every requested
tag, `exclude_tags` drops cases with any listed tag, and both filter before `--limit`; verification tags are not required by default.
See the [eval README](../../README.md) for execution commands.
