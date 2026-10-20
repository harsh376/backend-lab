# Evidence-Backed Answers

See [the one-pager](ONE_PAGER.md) for the project scope.

## Serve local model if needed

```shell
ollama run qwen3.8
```

## Run the compose stacks

```sh
docker compose -f compose/elasticsearch.yaml up -d --wait
GIT_COMMIT_SHA=$(git rev-parse HEAD) docker compose -f compose/temporal.yaml up --build
```

The image retains this SHA and Langfuse records it as the `release` field. For
processes running outside Docker, set `GIT_COMMIT_SHA` in their environment.
If unset, release is omitted. A SHA identifies committed code; use a clean
checkout for a reproducible baseline.

The Temporal stack starts Temporal, the answer worker, and the MCP HTTP server.
Rebuild with `--build` after changing Python code.

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
