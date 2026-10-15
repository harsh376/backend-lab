# Evidence-Backed Answers

See [the one-pager](ONE_PAGER.md) for the project scope.

## Run the compose stacks

```sh
docker compose -f compose/elasticsearch.yaml up -d --wait
docker compose -f compose/temporal.yaml up -d --build
```

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

## Run the workflow directly outside Docker

With the stack running, submit a question directly to Temporal:

```sh
uv run python -m apps.mcp.agent.workflow
```

## Langfuse tracing

Use Langfuse Cloud's free Hobby plan. Create an account and project, then generate
API keys in the project's settings. Set these in `compose/.env`:

```dotenv
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_BASE_URL=https://cloud.langfuse.com
LANGFUSE_TRACING_ENVIRONMENT=local
```

Use the URL for the region where you created the project: EU is
`https://cloud.langfuse.com`, US is `https://us.cloud.langfuse.com`, and Japan is
`https://jp.cloud.langfuse.com`. Keep real credentials out of version control.
The Hobby plan currently includes 50,000 units per month, 30 days of data access,
and two users; see <https://langfuse.com/pricing> for current limits. Units are
telemetry billing units, not model tokens or a count of answer runs.

Then rebuild/recreate the MCP stack:

```sh
docker compose -f compose/temporal.yaml up -d --build
```

Without both keys, tracing is disabled. Set `LANGFUSE_TRACING_ENABLED=false` to
explicitly disable it. Host processes read the same environment variables directly;
they do not automatically load `compose/.env`.

Submit an answer and open Langfuse's Traces view. The `mcp.answer` trace contains
`retrieve_answer_evidence` and `synthesize_answer` observations; activity retries
create separate observations with Temporal run ID, activity ID, and attempt metadata.
Trace context is persisted in the workflow input and forwarded to synthesis, so
workers can join the submission trace across processes and restarts. No tracing
code executes inside the deterministic workflow. Direct workflow submissions without
trace context produce separate activity traces correlated by workflow metadata.
`mcp.get_answer` polls are independent traces correlated through `answer_id`.

Observation inputs include the question and retrieval limit, the full retrieved
passages supplied to synthesis, and the run ID supplied to polling. These inputs
are exported to your configured Langfuse instance. Outputs summarize passage
IDs/corpus versions, provider, abstention, citation IDs, and status. The current
extractive baseline is a span, not an LLM generation, and reports no fabricated
usage or cost. When adding a real model provider, instrument its actual call as a
Langfuse generation and attach response usage/cost there.

The SDK batches asynchronously and shuts down on normal process exit. Forced
termination can lose buffered telemetry; traces are not a durable accounting ledger.
Langfuse Cloud hosts the observability backend; no local Langfuse services are needed.
