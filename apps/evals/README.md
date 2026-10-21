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
Use answers.run_evals with limit 5, tags ["page_verified"], timeout 120,
and retrieval_k 5. Poll answers.get_evals until finished and show the summary.
```

`run_evals` arguments:

```json
{
  "limit": 5,
  "tags": ["page_verified"],
  "timeout": 120,
  "retrieval_k": 5,
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

Defaults: `limit=3`, `tags=["page_verified"]`, `timeout=120`, `retrieval_k=5`.
Tags require all matches; pass `tags=[]` to disable tag filtering.
The eval workflow validates arguments and loads and selects cases on its worker.
Invalid arguments, missing cases, or invalid datasets fail the workflow.
Completed results include answer correctness, per-case AP@k/RR@k, and a
MAP@k/MRR@k summary. Retrieval metrics require `page_verified` cases.

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
Each eval execution appears as one local-data experiment, with one `eval_case`
trace per case. Completed `get_evals` responses include `experiment_id`, an
`experiment_url` when the project can be resolved, and `coverage` counts.
Open that URL and select a previous run as the baseline to inspect score changes
and drill into cases and their linked answer traces.

In the experiment comparison, the mean of `reciprocal_rank_at_5` is MRR@5 and
the mean of `ap_at_5` is MAP@5. Score names include the actual cutoff, so different
cutoffs cannot be combined. Zero is a valid score; unavailable metrics are
unscored. Check `coverage` and the summary's metric counts alongside averages:
failed or ineligible cases do not contribute to retrieval means.

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
records the dataset content hash, configured commit, cutoff, models, and evaluator
version. Compare the same case selection and dataset hash across runs.

This integration requires Langfuse v4 experiment ingestion. Results may take a
short time to appear after completion. Tracing disabled or an unavailable project
lookup does not prevent Temporal from returning evaluation results.

`experiment_name` is optional and must be nonblank when supplied. It sets the
displayed Langfuse experiment name; otherwise the workflow/execution IDs are used.
Names do not determine experiment identity: repeating a name creates a separate
run, and Temporal IDs remain in metadata for correlation.
