# Evidence-Backed Answers

See [the one-pager](ONE_PAGER.md) for the project scope.

## Tasks

1. Define request, result, citation and run-status models.
2. Add PostgreSQL tables for runs, evidence, configuration and provider costs.
3. Set up Elasticsearch and index a small, versioned KILT corpus subset using Temporal.
4. Implement retrieval and expose the `search` and `get_passage` MCP tools.
5. Build the Temporal answer workflow with a fake model provider.
6. Expose `answer` and `get_answer` MCP tools.
7. Add budget reservations, provider-call tracking and cost reconciliation.
8. Connect a real model provider for answer generation and evidence verification; abstain when support cannot be established.
9. Add traces and links to workflow history, evidence and cost records.
10. Test the complete question-to-answer flow and recovery after a worker interruption.
11. Expand ingestion to the full corpus.
12. Add an experiment runner and report answer correctness, retrieval quality and evidence support separately.

## Basic Temporal agent

The initial agent uses a fake, extractive synthesis provider: it quotes the
highest-ranked original paragraph. This exercises retrieval, durable activity
outputs and cited results without API credentials. It does **not** yet produce
concise model answers or verify semantic support. Empty retrieval and invalid
citations cause abstention. `AnswerActivities` accepts an async synthesis callable for
replacing the fake provider later.

Configuration comes from `apps.api.config.Settings`, with environment overrides
for `TEMPORAL_ADDRESS`, `ELASTICSEARCH_URL`, and `KILT_INDEX`. Host defaults are
`localhost:7233`, `http://localhost:9200`, and `kilt`. The `compose/.env` and
`compose/.env.example` files configure container addresses for Compose; host
commands do not automatically load them.

Start Elasticsearch and Temporal, import KILT with `KiltService`, then run:

```sh
export TEMPORAL_ADDRESS=localhost:7233
export ELASTICSEARCH_URL=http://localhost:9200
export KILT_INDEX=kilt-v1
uv run python -m apps.mcp.agent.worker
# In another terminal, with the same environment:
uv run python -m apps.mcp.server
```

Configure an MCP host to launch the server command using stdio. Call
`answer(question, limit=5)` to receive a run ID, then `get_answer(run_id)` until
its status is `COMPLETED` (or a terminal failure status). Completed results
contain `short_answer`, `explanation`, `citations`, `abstained` and `provider`.
Temporal retains the retrieved evidence and synthesis output in activity history.
The worker uses the `kilt-answers` queue and bounded activity retries/timeouts.

Each citation contains the index name, article/paragraph identity and original
paragraph text. Use an immutable index name for each corpus version and import
into that same index; the service cannot enforce immutability. Retrieval ranks
paragraphs from matching articles by query-term overlap, a deliberately basic
baseline. Large article payloads and provider idempotency need attention before
scaling. This increment does not implement budgets, usage/cost records, semantic
verification, trace links, or the separate `search`/`get_passage` MCP tools.

Run baseline checks with `uv run pytest apps/mcp/agent/test_agent.py`.
A live Temporal/Elasticsearch run and worker-interruption demonstration are still
needed to validate deployment and recovery.

## Query from the console

With KILT imported, start Elasticsearch and then Temporal, which also runs the
agent worker in a container:

```sh
docker compose -f compose/elasticsearch.yaml up -d --wait
docker compose -f compose/temporal.yaml up -d --build
```

Rebuild with `--build` after changing agent code. To run the worker on the host
instead, use `uv run python -m apps.mcp.agent.worker`.

Submit a question directly to Temporal and wait for the answer:

```sh
uv run python -m apps.mcp.agent.workflow "When did Arthur's Magazine begin publication?"
```

No MCP server or host is needed. The command prints the structured answer with
citations to stdout and reads `TEMPORAL_ADDRESS` to select Temporal.
The containerised worker defaults to the `kilt` index; set `KILT_INDEX` when
starting the stack to use another. The
current synthesis provider is still the extractive baseline.
