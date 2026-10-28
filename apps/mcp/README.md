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

`limit` is the number of articles to retrieve (1–100, default 5). Every
retrieved article is returned as one `ArticleEvidence` in a list and supplied
in full to synthesis, grouped into its original
paragraphs. Section headings, empty paragraphs, and paragraph IDs are preserved;
there is no paragraph-overlap scoring or second selection cutoff. Citations and
verification continue to use the original paragraph IDs. Large inputs may exceed
the model context window; articles are not silently truncated.

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

Call `run_evals` with optional `case_id`, `limit` (default `3` for both local and
hosted datasets; pass `null` for all eligible cases), `tags` (defaults
to `["page_verified"]`; pass `[]` to disable filtering; all
must match), and `timeout` (default `600`, positive and at most `3600` seconds).
It selects eligible cases from the bundled KILT dev dataset, excluding
`rejected` cases, and returns an eval `run_id` and `RUNNING` status. Poll
`get_evals` with that ID; on completion it returns `results` containing
per-case execution output and judgments keyed by evaluator name, such as
`evaluators.answer_correctness`.

Use `run_retrieval_evals` for independent retrieval recall. It accepts the same
case/dataset filters plus `retrieval_limit` (1–100, default 100 articles per query).
Poll `get_evals` for ranked page IDs, latency, per-case recall@5/10/50/100, and
`retrieval_summary`. It needs the eval worker and Elasticsearch; no answer worker
or judge is used. Full article text stays inside the eval activity.

E2E eval activities invoke `AnswerWorkflow` directly through Temporal. Each case
has separate, linked answer and eval traces sharing the eval run session ID.
Gold labels are used for judging and are not sent to the answer workflow.
See the [eval README](../evals/README.md) for tool usage, judge configuration,
and result details.
