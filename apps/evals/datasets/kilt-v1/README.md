# KILT v1 dataset

Run commands from the repository root. The bundled `dev.json` contains
45 cases (30 NQ and 15 HotpotQA); `manifest.json` records source hashes,
sampling settings, counts, and corpus source identity.

Corpus verification has already been run and its tags are saved in `dev.json`:

- 45/45 cases have `page_verified`.
- 33/45 cases have `passage_verified` (the tag for paragraph-range and character-offset checks).

Human review of answer correctness and semantic support is still pending;
the saved verification tags record structural corpus checks. The next step is
to run a baseline evaluation and inspect its failures. Refresh corpus verification
when the dataset or corpus changes.

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

## Case format and selection

Each case has `case_id`, `group_id`, `question`, `source`, `accepted_answers`,
`answerable`, `evidence_sets`, and `tags`. Source metadata retains the dataset,
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
tag and filters before `--limit`; verification tags are not required by default.
See the [eval README](../../README.md) for execution commands.
