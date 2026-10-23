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
Use answers.run_evals with limit 5, tags ["page_verified"], timeout 120. Poll answers.get_evals until finished and show the summary.
```

`run_evals` arguments:

```json
{
  "limit": 5,
  "tags": ["page_verified"],
  "timeout": 120,
  "experiment_name": "BM25 baseline"
}
```

For one case:

```json
{"case_id": "nq-dev-737118727843422688"}
```

Poll `get_evals` with the returned ID:

```json
{"run_id": "kilt-eval-<returned-id>"}
```

Defaults: `limit=3`, `tags=["page_verified"]`, `timeout=120`.
Tags require all matches; pass `tags=[]` to disable tag filtering.

### Run a hosted Langfuse dataset

Create a dataset in the configured Langfuse project (for example,
`basline-v5-errors`) and add the cases you want to rerun. Then call:

```json
{
  "hosted_dataset": "basline-v5-errors",
  "experiment_name": "Error cases after retrieval changes"
}
```

With `hosted_dataset`, omitted `limit` runs **all active items**, and omitted `tags`
applies no tag filter. `case_id` selects `input.case_id`; `tags` filters
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
