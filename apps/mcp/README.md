# Evidence-Backed Answers

See [the one-pager](ONE_PAGER.md) for the project scope.

## Serve local model if needed

```shell
ollama run qwen3.8
```

## Run the compose stacks

```sh
docker compose -f compose/elasticsearch.yaml up -d --wait
docker compose -f compose/temporal.yaml up -d --wait
GIT_COMMIT_SHA=$(git rev-parse HEAD) docker compose -f compose/mcp.yaml up --build
```

The image retains this SHA and Langfuse records it as the `release` field. For
processes running outside Docker, set `GIT_COMMIT_SHA` in their environment.
If unset, release is omitted. A SHA identifies committed code; use a clean
checkout for a reproducible baseline.

`temporal.yaml` owns the Temporal server, initialization, and storage.
`mcp.yaml` owns the answer worker and MCP HTTP server. Start infrastructure
first, then run MCP in its own terminal. Keep the same Compose project name
across commands to share the network with Elasticsearch. The commands above
use the same default project name because all files live in `compose/`.

After changing Python code, rebuild only the affected application services:

```sh
docker compose -f compose/mcp.yaml up --build
```

Temporal infrastructure does not need restarting for application code changes.

- Temporal Web UI: <http://localhost:8233>
- MCP Streamable HTTP endpoint: <http://localhost:8001/mcp>
- Elasticsearch: <http://localhost:9200>

## Query through Codex

Register MCP Server from the CLI:

```sh
codex mcp add answers --url http://localhost:8001/mcp
codex mcp list
```

Keep the stack running, then enter this prompt in Codex:

```text
Use the answers MCP tool to answer “Who wrote Photograph by Ringo Starr?”
Poll get_answer until it completes and show the citations.
```

Codex submits the equivalent of:

```json
{"question": "Who wrote Photograph by Ringo Starr?", "limit": 5}
```

## Per-answer model budget

Supply an optional positive `budget_usd` when starting a run:

```json
{"question": "When did Arthur's Magazine begin publication?", "limit": 5, "budget_usd": 0.05}
```

## Retrying answer submissions

Use an optional `idempotency_key` to retry a submission without starting another
answer workflow:

```json
{"question": "When did Arthur's Magazine begin publication?", "limit": 5, "idempotency_key": "eval:baseline-001:case-001:attempt-1"}
```

## Run dataset evaluations

Start the eval worker alongside the answer stack:

```sh
docker compose -f compose/evals.yaml up --build
```

Call `run_evals` with optional `case_id`, `limit` (default `1`), `tags` (all
must match), and `timeout` (default `120`, positive and at most `3600` seconds).
It selects eligible cases from the bundled KILT dev dataset, excluding
`rejected` cases, and returns an eval `run_id` and `RUNNING` status. Poll
`get_evals` with that ID; on completion it returns `results` containing
per-case execution output and judgments keyed by evaluator name, such as
`evaluators.answer_correctness`.

Eval activities invoke `AnswerWorkflow` directly through Temporal. Each case
has separate, linked answer and eval traces sharing the eval run session ID.
Gold labels are used for judging and are not sent to the answer workflow.
See the [eval README](../evals/README.md) for CLI commands, judge configuration,
and result details.
