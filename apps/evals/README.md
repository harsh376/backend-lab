# Evaluations

Run commands from the repository root.

## Start services

Use a separate terminal for each stack. Wait for Elasticsearch and Temporal
before starting the application workers.

```sh
# Terminal 1
docker compose -f compose/elasticsearch.yaml up

# Terminal 2
docker compose -f compose/temporal.yaml up

# Terminal 3
docker compose -f compose/mcp.yaml up --build

# Terminal 4
docker compose -f compose/evals.yaml up --build
```

Use the same Compose project name across terminals. Leave other stacks running
when Compose reports orphan containers; do not use `--remove-orphans`.

## Run an evaluation

Register the MCP server:

```sh
codex mcp add answers --url http://localhost:8001/mcp
```

Ask Codex:

```text
Use answers.run_evals with limit 5, tags ["page_verified"], timeout 600. Poll answers.get_evals until finished and show the summary.
```

`run_evals` arguments:

```json
{
  "limit": 5,
  "tags": ["page_verified"],
  "timeout": 600,
  "experiment_name": "BM25 baseline"
}
```

To establish a synthesis-only correctness baseline, pass
`verification_enabled=false` to `run_evals`. Verification defaults to enabled.
The flag is stored in workflow inputs and experiment metadata; disabling it skips
both the verifier model call and its budget quote.

For one case:

```json
{"case_id": "nq-dev-737118727843422688"}
```

Poll `get_evals` with the returned ID:

```json
{"run_id": "kilt-eval-<returned-id>"}
```

The case limit defaults to `3` for both local and hosted datasets. Pass
`limit=null` to run all eligible cases for either source. Local defaults:
`tags=["page_verified"]`, `timeout=600` for answer evals.
Tags require all matches; pass `tags=[]` to disable tag filtering.

All answer and eval timeouts are fields on `Settings` in `backend/config.py`.
Consumers construct `Settings()` at runtime. Fields beginning with `timeout_`
read matching `TIMEOUT_*` environment variables; Compose forwards these without
providing separate defaults. For example:

```dotenv
TIMEOUT_MODEL_REQUEST_SECONDS=180
TIMEOUT_ANSWER_EVAL_SECONDS=600
TIMEOUT_RETRIEVAL_EVAL_SECONDS=120
```

Activity and scoring deadlines are properties derived from the model ceiling
(`TIMEOUT_MODEL_REQUEST_MAX_SECONDS`) and activity overhead
(`TIMEOUT_ACTIVITY_OVERHEAD_SECONDS`). Increase the ceiling too if raising the
model request timeout above it. The `timeout` tool argument still overrides an
individual run's answer or retrieval deadline.

At submission, only timeout/retry fields are copied into workflow inputs.
Workflows reconstruct `Settings` from that snapshot, so environment changes
cannot alter replay. No credentials or other application settings are recorded.
Older workflows without a snapshot use the declared Settings defaults.

Answer evals explicitly retrieve the top **10 articles** for answer generation. The
`run_evals.limit` argument selects dataset cases, not articles. Retrieval uses a
larger internal candidate pool for ranking before returning those 10 articles.
Standalone retrieval evals configure their output size with `retrieval_limit`.

### Compact synthesis context

Synthesis defaults to **Compact**: rank original paragraphs across all retrieved
articles with the existing candidate-local BM25 window scorer, then select at
most 12 paragraphs within an estimated 5,000-token input budget. Titles are
included in scoring. After selecting a paragraph, other paragraphs from the same
article receive a diminishing score (`score / (1 + selected_count)`) to encourage
multi-article evidence. Ties follow retrieval and original paragraph order.
Empty paragraphs, section markers, and duplicate normalized text are excluded.
Selected paragraphs are grouped by article and retain their original offsets,
text, and citation identifiers. A model citation to a retrieved but omitted
paragraph is rejected.

Configure the answer worker through environment variables (also forwarded by
`compose/mcp.yaml`):

```dotenv
MCP_ANSWER_CONTEXT_MODE=compact
MCP_ANSWER_CONTEXT_MAX_TOKENS=5000
MCP_ANSWER_CONTEXT_MAX_PARAGRAPHS=12
MCP_ANSWER_PASSAGE_RANKER=bm25
```

Paragraph scoring is delegated to a `PassageRanker`
(`backend/services/passage_ranking`), selected by `MCP_ANSWER_PASSAGE_RANKER`.
Rankers receive each candidate paragraph with its article's zero-based retrieval
rank and return one score per candidate; diversity, deduplication, and the
token/paragraph budget remain in compact synthesis. `bm25` is the window scorer
described above. Retrieval eval results record the active `passage_ranker`.

The token budget includes the serialized system/user messages, question,
citation metadata, response schema, and a small framing allowance. It excludes
output tokens, which remain controlled by `MCP_ANSWER_MAX_TOKENS`. LiteLLM uses a
generic tokenizer for unknown models, so this is an estimate; actual provider
counts may differ, particularly for local Ollama models.

The 12/5000 default comes from a 2026-10-29 sweep over the 33 `passage_verified`
cases at `retrieval_limit=10` (recall@10 0.788 in every run). The paragraph cap
was always the binding limit:

| Paragraphs / tokens | `passage_recall@10` |
|---|---|
| 5 / 2000 | 0.303 |
| 8 / 3500 | 0.379 |
| 12 / 5000 | 0.449 |
| 20 / 8000 | 0.520 |
| full | 0.788 |

On `ollama_chat/qwen3.8`, prefill runs at roughly 480 tokens/s, so 12/5000 adds
about 6 seconds of synthesis latency over 5/2000; larger settings trade
diminishing recall for more latency.
Whole paragraphs that do not fit are skipped rather than truncated. If no
paragraph fits, synthesis abstains without a model call. This can lose evidence
in unusually large paragraphs and must be checked in the next correctness eval.
No automatic full-article retry is made, keeping the context bound predictable.
Selection runs outside the worker event loop, uses no model calls, and is shared
by budget quoting and generation. Retrieval and citation-only verification remain
unchanged; retrieval-to-synthesis Temporal payloads still carry complete articles.

Set `MCP_ANSWER_CONTEXT_MODE=full` for the full-article control. Full mode ignores
both Compact limits and retains the previous `article-synthesis-v3` prompt.
Compact generations use `compact-synthesis-v1`; inspect generation inputs and
reported prompt tokens alongside that version. Rebuild/restart the answer worker
when changing code or configuration:

```sh
docker compose -f compose/mcp.yaml up -d --build agent-worker
```

Then use the same cases, retrieval, synthesis/verifier/judge models, and corpus
as `answer-top10-003`, with a unique experiment name such as `answer-compact-001`.
Compare correctness, scored coverage, prompt tokens, synthesis/verification
latencies, and total answer latency. The per-case `elapsed_seconds` measures
answer execution before the correctness judge; whole eval-case tracing also
includes judging. Latency and correctness improvements have not yet been measured
for Compact.

### Run a hosted Langfuse dataset

Create a dataset in the configured Langfuse project (for example,
`basline-v5-errors`) and add the cases you want to rerun. Then call:

```json
{
  "hosted_dataset": "basline-v5-errors",
  "limit": null,
  "experiment_name": "Error cases after retrieval changes"
}
```

With `hosted_dataset`, omitted `limit` runs up to **three eligible items**, just
as for a local dataset. Explicit `limit=null` runs all eligible items. Omitted
`tags` applies no tag filter. `case_id` selects `input.case_id`; `tags` filters
`input.tags`. Archived items and cases tagged `rejected` are excluded. Without
`hosted_dataset`, the local defaults above still apply.

The hosted item's **input is the complete original EvalCase**, copied directly
from an `eval_case` observation's input. Leave **expected output empty**. For example:

```json
{
  "input": {
    "case_id": "nq-dev-8239463385147663167",
    "group_id": "question-example",
    "question": "is jaffa cakes a biscuit or a cake",
    "source": {
      "dataset": "nq",
      "split": "dev",
      "record_id": "8239463385147663167",
      "filename": "nq-dev.jsonl",
      "original_output": {}
    },
    "accepted_answers": ["cake", "cakes"],
    "answerable": true,
    "evidence_sets": [],
    "tags": ["citation"]
  },
  "expected_output": null,
  "metadata": {"original_eval_run_id": "kilt-eval-..."}
}
```

`case_from_item` validates `item.input` directly with `EvalCase.model_validate`,
using the same contract as local cases. No fields are reconstructed from expected
output or metadata. Metadata remains optional provenance; its tags do not override
`input.tags`. Reference answers, answerability, evidence alternatives and paragraph
ranges, case/group identity, and tags are preserved from input. Partial old-style
items with only a question in input must be updated to the complete case.

Only execution-source provenance is updated: `source.kind`, `source.dataset`,
`source.dataset_id`, `source.record_id`, and `source.version` describe the hosted
snapshot and provide canonical dataset-item links. Original `source.original_output`,
`source.split`, and `source.filename` are retained. Case IDs must be unique among
active items. Missing/invalid cases fail loading before answers run.

The `eval_case` span input contains the entire case via `model_dump(mode="json")`.
The experiment's expected-output attribute still describes the case's reference
fields for display; the hosted loader does not read it. Span changes apply to new
executions; existing observations are unchanged.

The worker reads all pages at one UTC snapshot timestamp, then stores the selected
cases in Temporal history. Dataset edits after loading do not change that run.
Experiment observations carry the hosted dataset ID, item IDs, name and snapshot
timestamp; they do not claim the local dataset hash. Dataset reads require
`LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, and the appropriate
`LANGFUSE_BASE_URL` on the eval worker, and work with tracing disabled. Reporting
the experiment in Langfuse still requires tracing to be enabled.

The eval workflow validates arguments and loads and selects cases on its worker.
Invalid arguments, missing cases, or invalid datasets fail the workflow.
Completed results include final-answer correctness and a mean correctness summary
with a count of scored cases. Intermediate operations are not evaluated.

The correctness judge (`EVAL_JUDGE_MODEL`, defaulting to `MCP_ANSWER_MODEL`) runs
at `EVAL_JUDGE_TEMPERATURE`, default `0`, and each judgment records the
temperature it used. At the model's default sampling, an offline re-judge of 66
saved answers (2026-10-29) flipped verdicts on 4 answers across 3 samples and
disagreed with hand labels on 5 of 198 judgments; at temperature 0 it was
deterministic and matched every label. Set `EVAL_JUDGE_TEMPERATURE=` (empty) to
use the provider default for models that reject temperature overrides, such as
some OpenAI reasoning models. Synthesis and verification keep their provider
defaults. Correctness from runs before this change was judged at the model
default and is not directly comparable.

## Worker commands

```sh
# Logs
docker compose -f compose/evals.yaml logs -f eval-worker

# Scale the pool
docker compose -f compose/evals.yaml up -d --scale eval-worker=2

# Stop only eval workers
docker compose -f compose/evals.yaml stop

# Run a host worker instead of Docker
uv run python -m apps.evals.worker
```

Dataset build and corpus verification commands: [KILT v1 README](datasets/kilt-v1/README.md).

## Comparing runs in Langfuse

Temporal owns execution and scoring; Langfuse's experiment runner is not used.
Each eval execution appears as one experiment, with one `eval_case`
trace per case. Completed `get_evals` responses include `experiment_id`, an
`experiment_url` when the project can be resolved, and `coverage` counts.
Open that URL and select a previous run as the baseline to inspect score changes
and drill into cases and their linked answer traces.

In the experiment comparison, `correctness` measures final-answer quality.
Zero is a valid score; unavailable judgments are unscored. Check `coverage` and
`summary.correctness_count` alongside averages: failed or ineligible cases do not
contribute to the mean.

Experiment IDs include the Temporal workflow execution ID; case IDs are stable
across runs. All evaluator observations inherit experiment and item attributes.
Answer execution continues within the experiment case trace, so Total Cost ($)
includes answer synthesis, verification, and judge generations. Detailed costs are
available on the individual generation observations in the trace. Costs are not
emitted as evaluation scores, whose display rounds small USD values.
Experiment and item baggage travels with the trace context in Temporal payloads
and is restored before answer activity spans start. A shared trace ID alone does
not attribute those generations to the experiment's cost totals.
Costs use LiteLLM pricing estimates.
These changes apply to new runs; historical experiments are not backfilled. No hosted Langfuse dataset is required. Local
experiments omit `langfuse.experiment.dataset.id`: that field must refer to a real
hosted dataset, because the UI uses it to link input cells to dataset items.
The local dataset label is recorded in experiment metadata instead. Metadata
records the dataset content hash, configured commit, models, and evaluator
version. Compare the same case selection and dataset hash across runs.

This integration requires Langfuse v4 experiment ingestion. Results may take a
short time to appear after completion. Tracing disabled or an unavailable project
lookup does not prevent Temporal from returning evaluation results.

`experiment_name` is optional and must be nonblank when supplied. It sets the
displayed Langfuse experiment name; otherwise the workflow/execution IDs are used.
Names do not determine experiment identity: repeating a name creates a separate
run, and Temporal IDs remain in metadata for correlation. Hosted runs attach the
real Langfuse dataset ID and canonical item IDs so items link to their dataset.

## Export an error-analysis dataset

Call `create_dataset_from_eval` after an eval completes:

```json
{
  "eval_name": "test-v5",
  "score_filters": [
    {"name": "answer_correctness", "operator": "eq", "value": 0}
  ],
  "dataset_name": "test-v5-correctness-errors"
}
```

Filters combine with AND. `name` selects an evaluator; `score_field` defaults to
`correctness`. Operators are `eq`, `ne`, `lt`, `lte`, `gt`, and `gte`. Missing,
null, boolean, and nonnumeric scores are excluded. An empty filter list is rejected.
No matches returns `NO_MATCHES` without creating a dataset.

`eval_name` selects the `experiment_name` supplied to `run_evals`. Names must
identify exactly one retained Temporal eval run; missing or duplicate names are
rejected. Use unique experiment names. New runs store the name in a Temporal memo;
older runs are resolved from their original workflow input. Resolution requires
Temporal workflow visibility and retained histories for older runs. The response
includes both `eval_name` and the resolved `run_id` for provenance.

The tool uses the Langfuse SDK and requires configured public/secret keys even
when tracing is disabled. It copies original case snapshots and reference outputs,
links the eval trace, and stores scores, reasons, and source run metadata. New runs
retain snapshots in Temporal results; older runs require their original
`eval_case` trace inputs to remain available in Langfuse. Current local dataset
contents are never substituted for missing historical snapshots.

The response includes the dataset ID, URL when project lookup succeeds, matched,
created, and existing counts, and per-case failures. Retry identical arguments
following `PARTIAL` or a connection failure: deterministic item IDs avoid duplicate
items, and existing items are skipped. A dataset name belonging to a different
run/filter export is rejected. Do not edit or archive exported items while retrying.

Rerun the resulting cases with `run_evals(hosted_dataset="test-v5-correctness-errors")`.
Restart the MCP server and eval worker after deploying these changes to expose the
new tool and persist snapshots in new runs.

## Standalone retrieval evaluations

Use `run_retrieval_evals` to measure the production retriever without answer
synthesis, verification, or a correctness judge. It reuses `load_eval_cases`,
including local/hosted dataset selection, `case_id`, tags, rejected-case exclusion,
and case limits. `run_evals` now scores answer correctness only.

```json
{
  "experiment_name": "retrieval-baseline",
  "limit": 5,
  "retrieval_limit": 100
}
```

For a hosted dataset, add `hosted_dataset`; use `limit=null` for all eligible cases.
The default case limit is three for either source. Local cases default to
`tags=["page_verified"]`; hosted cases have no default tag filter. Pass `tags=[]`
to disable tag filtering. `timeout` bounds each retrieval query and defaults to
120 seconds. `retrieval_limit` selects articles per query (1–100, default 100),
independently of the number of eval cases.

Poll **`get_evals`** with the returned `kilt-eval-retrieval-...` ID. Results contain
ranked Wikipedia page IDs, the corpus version, requested article limit, retrieval
latency (`elapsed_seconds`), and `evaluators.retrieval_recall_at_k`.
`retrieval_summary` reports macro averages and scored-case counts; `coverage`
includes scored/skipped counts for each cutoff. Retrieval runs omit the answer
correctness `summary`. Scores are also reported to Langfuse experiments as
numeric `recall@K` and `passage_recall@K` metrics. Failed retrieval activities remain unscored and do not
stop subsequent cases. Existing dataset export also supports retrieval scores;
use `name="retrieval_recall_at_k"` and, for example, `score_field="recall@50"`.

Recall is the fraction of distinct reference Wikipedia pages retrieved, taking
the **maximum across alternative evidence sets**. Repeated references to a page
count once, and multi-page sets earn partial credit. Fixed cutoffs are **5, 10,
50, and 100**, scored only at or below `retrieval_limit`. A completed query with
no hits scores zero. Unanswerable cases or cases without reference evidence are
unscored. Compare the same cases, corpus, cutoffs, and scored-case coverage.

`passage_recall@K` measures the fraction of distinct reference paragraphs present
in the **synthesis input**: the eval passes the top K retrieved articles through
the configured synthesis service's `prepare_input` (the same selection the answer
worker applies before quoting and generation) and scores the paragraphs it keeps,
taking the maximum across alternative evidence sets. Each cutoff simulates a
retrieval limit of K, so compact mode packs each cutoff independently. Accepted
passages come from the inclusive paragraph ranges in `evidence_sets`; overlapping
ranges and repeated paragraphs count once. In `full` mode every retrieved
paragraph is kept; in `compact` mode a reference paragraph in a retrieved article
earns no credit unless it survives ranking and the
`MCP_ANSWER_CONTEXT_MAX_TOKENS`/`MCP_ANSWER_CONTEXT_MAX_PARAGRAPHS` budget, so
configure the eval worker's context settings to match the answer worker. Results
record `synthesis_service` and per-cutoff `synthesis_paragraph_counts`, without
article text. Passage scores require `passage_verified`; page-only verified cases
remain scored for page recall and are skipped for passage recall. The same
cutoffs, macro averages, scored/skipped coverage, Langfuse reporting, and export
filters apply (use `score_field="passage_recall@50"`). Scores from
`article-passage-recall-v3` measured availability in whole retrieved articles and
are not comparable.

Retrieval and scoring execute inside one eval activity using the same
`KiltService.asearch_evidences` path as the answer worker. Full article text never
enters Temporal activity outputs or workflow results for retrieval evals. No
answer worker is needed and no model is called; synthesis preparation only counts
tokens for `MCP_ANSWER_MODEL`, but the worker builds that model's client at
startup, so OpenAI/Anthropic models still require their API key to be set. The
eval worker needs Elasticsearch:
configure `ELASTICSEARCH_URL` and `KILT_INDEX` (Compose defaults to
`http://elasticsearch:9200` and `kilt`). Rebuild/restart the MCP server and eval
worker to expose the tool. Historical runs are not backfilled.

Answer results also omit full retrieved articles; compact candidate IDs and cited
paragraphs remain available. Rebuild/restart the answer worker to apply that
output change. Answer workflows still pass article evidence between
retrieval and synthesis activities, so unusually large synthesis inputs can
still require external payload storage or a different activity boundary.
