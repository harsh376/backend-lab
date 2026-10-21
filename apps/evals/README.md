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
  "retrieval_k": 5
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
