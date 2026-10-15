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

Tracing initializes before the server accepts requests, so the SDK wraps both
tools consistently. The tool decorators populate inputs, outputs, and metadata on
the existing SDK `answer` and `get_answer` spans without creating extra spans.
Submit an answer and open Langfuse's Traces view. The submission trace contains
`retrieve_answer_evidence` and `synthesize_answer` observations; activity retries
create separate observations with Temporal run ID, activity ID, and attempt metadata.
Trace context is persisted in the workflow input and forwarded to synthesis, so
workers can join the submission trace across processes and restarts. No tracing
code executes inside the deterministic workflow. Direct workflow submissions without
trace context produce separate activity traces correlated by workflow metadata.
`get_answer` polls are independent traces correlated through `answer_id`.

For Codex clients that send `_meta.threadId` on MCP tool requests, submission,
worker observations, and polls are grouped in one Langfuse session named
`codex:<threadId>`. The middleware reads this metadata automatically; no tool
argument or model-generated identifier is needed. The session ID is persisted
in the Temporal input and forwarded to synthesis, alongside trace context.
Multiple answer runs retain their own `answer_id` within the chat session.
Polling belongs to the calling chat; polling an answer from a different chat
therefore appears in that different chat's session.

Missing or invalid thread metadata leaves calls ungrouped. Direct workflow
submissions also remain ungrouped unless their input supplies `session_id`.
Transport connection IDs are never used as chat IDs. Thread metadata is a
client-provided observability label, not an authentication identity.

After rebuilding the stack, verify the installed Codex client's behavior by
submitting and polling answers from two chats: Langfuse should show distinct
`codex:<threadId>` sessions. Resume the first chat and submit another answer;
it should join its original session. If sessions are absent, inspect only the
incoming `_meta.threadId` field to confirm whether that client sends it; avoid
logging full request metadata or credentials.


Observation inputs include the question and retrieval limit, the full retrieved
passages supplied to synthesis, and the run ID supplied to polling. These inputs
are exported to your configured Langfuse instance. Outputs capture the returned
passages, synthesis result, submission status, and polling result. The current
extractive baseline is a span, not an LLM generation, and reports no fabricated
usage or cost. When adding a real model provider, instrument its actual call as a
Langfuse generation and attach response usage/cost there.

The SDK batches asynchronously and shuts down on normal process exit. Forced
termination can lose buffered telemetry; traces are not a durable accounting ledger.
Langfuse Cloud hosts the observability backend; no local Langfuse services are needed.
