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

## OpenAI and Claude synthesis through LiteLLM

Synthesis lives in `backend/services/answer_synthesis/answer_synthesis.py`.
`AnswerSynthesisService`
accepts a `SynthesisAdapter` implementing `async synthesize(data) -> AnswerResult`
and applies shared citation identity checks. `ExtractiveSynthesis` supplies the
baseline; `LiteLLMSynthesis` adapts OpenAI and Claude through LiteLLM. To add a
synthesis variation, implement that interface and inject it into the service;
the MCP tools and Temporal workflow do not need to change. Both LiteLLM adapters
compose the structured-output client in `backend/llm.py`; neither inherits from
it. Pass `model=` to inject any client implementing `StructuredModel`, or supply
settings to construct the default client. The shared client handles provider
calls, telemetry, usage and cost; adapters own prompts and response parsing.
The worker constructs
the LiteLLM adapter directly and supplies the Langfuse observation factory. Provider
rejections are translated into Temporal failures by the activity layer.

The worker always uses LiteLLM and defaults to
`MCP_ANSWER_MODEL=openai/gpt-5.6-terra`. Set the selected provider's key in
`compose/.env`; a missing key fails worker startup. For OpenAI:

```dotenv
MCP_ANSWER_MODEL=openai/gpt-5.6-terra
OPENAI_API_KEY=your-openai-api-key
```

Or for Claude:

```dotenv
MCP_ANSWER_MODEL=anthropic/claude-sonnet-5
ANTHROPIC_API_KEY=your-anthropic-api-key
```

Use a model available to your account that supports structured output through
LiteLLM. The model name is configurable; these are examples, not an allowlist.
Only the selected provider's key is required. Keys are passed only to the worker
container and are never included in workflow inputs or results. Keep real keys
out of version control.

Apply changes by rebuilding/recreating the worker:

```sh
docker compose -f compose/temporal.yaml up -d --build agent-worker
```

The existing `answer` and `get_answer` tools use the worker's configured model;
there is no model argument on the tools. For a worker started outside Docker,
export the same variables in its environment; `compose/.env` is not loaded by
Python automatically. Both Docker and direct workflow submissions use this worker
configuration. Switching models affects subsequent synthesis activities, including
retries, so finish existing runs before changing it for an experiment.

Optional settings are `MCP_ANSWER_MAX_TOKENS` (default `1024`) and
`MCP_ANSWER_TIMEOUT_SECONDS` (default `40`, maximum `45`, below the activity's
60-second timeout). LiteLLM retries and response caching are disabled; Temporal
retains its existing activity retry policy. Authentication, model-access and bad
request errors fail without retry. Transient errors can be retried by Temporal;
a timed-out provider call may still have executed and incurred cost.

Synthesis requests a strict JSON schema with `short_answer`, `explanation`,
`citation_ids` and `abstained`. The backend resolves citation IDs to the original
retrieved passages. Empty retrieval skips the model. Malformed, truncated,
refused or invalidly cited responses abstain, retaining any returned usage.
Citation identity is checked during synthesis; a separate verification activity
then checks semantic evidence support before returning a non-abstained answer.

Results include `provider`, `model`, normalized token `usage`, and
`estimated_cost_usd`. Cost is estimated from LiteLLM's pricing catalog and is null
when unavailable. Top-level fields describe synthesis; `verification` records the verifier
judgment (`supported`, `reason`), provider, model, usage and estimated cost
separately. Add the two costs only when both are known. These fields describe
the completed attempts, not all
retry attempts or total host spend, and are not a durable cost ledger or budget
enforcement mechanism. The extractive baseline returns empty usage and null cost.

## Answer verification

The workflow is retrieve → synthesize → verify → return. The separate
`AnswerVerificationService` in
`backend/services/answer_verification/answer_verification.py` accepts an
interchangeable adapter implementing `verify(data)`. The worker uses
`LiteLLMVerification`, which makes a fresh structured-output call containing the
question, candidate short answer, explanation and cited passages only.

The verifier checks that the answer addresses the question and that factual
claims in both answer fields are supported by the citations. Unsupported,
malformed, refused or truncated judgments produce an abstention with no short
answer or citations. Synthesis abstentions skip verification. Provider failures
follow the synthesis retry policy: configuration rejections fail immediately;
transient failures retry through Temporal and fail the run if exhausted.

By default verification uses `MCP_ANSWER_MODEL`. Optionally set
`MCP_VERIFIER_MODEL=anthropic/<model>` or `openai/<model>` in `compose/.env`.
The corresponding provider key must be present. It shares the answer token limit
and timeout settings. Rebuild the worker after changes. Each verification activity
has its own `verification_model` Langfuse generation with prompt version, usage
and estimated cost, joined to the submission trace and chat session.

This is a model judgment of evidence support, not a guarantee of factual
correctness. Audit judgments against manually reviewed examples before relying
on them as evaluation labels. The Temporal version marker preserves replay of
older histories that completed without verification; newly started runs include it.

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
passages, synthesis result, submission status, and polling result. The extractive
baseline is a span, not an LLM generation, and reports no fabricated usage or cost.
LiteLLM synthesis creates one nested `answer_model` generation per activity attempt,
under the existing synthesis observation. It records the configured model, prompt
version, model parameters, returned response model/ID, finish reason, usage and
estimated cost. It inherits the activity's trace and chat session; no LiteLLM
Langfuse callback is needed.

The SDK batches asynchronously and shuts down on normal process exit. Forced
termination can lose buffered telemetry; traces are not a durable accounting ledger.
Langfuse Cloud hosts the observability backend; no local Langfuse services are needed.

## Local models with Ollama on macOS

Run Ollama natively on your Mac for Apple GPU acceleration, then download a model:

```sh
ollama run qwen3.8
```

Set these values in `compose/.env`:

```dotenv
MCP_ANSWER_MODEL=ollama_chat/qwen3.8
MCP_VERIFIER_MODEL=
OLLAMA_API_BASE=http://host.docker.internal:11434
```

An empty verifier model uses the answer model. Ollama requires no cloud API key.
The shared adapter requests JSON schema output and disables thinking for local
requests to conserve the output budget and reduce latency. Existing response
validation and citation checks still apply.

Rebuild the worker:

```sh
docker compose -f compose/temporal.yaml up -d --build agent-worker
```

For a worker running directly on macOS, export `MCP_ANSWER_MODEL` and use
`OLLAMA_API_BASE=http://localhost:11434` (the Python default). If Docker cannot
reach Ollama, check from a container with
`curl http://host.docker.internal:11434/api/tags`. If necessary, quit the Ollama
app, run `OLLAMA_HOST=0.0.0.0:11434 ollama serve`, and retry. This binds Ollama to
all interfaces; use it only on a trusted network with appropriate firewall rules.
Keep Ollama running while the worker handles requests. Warm the model before
benchmarking: the first load may exceed the 40-second request timeout. Compare
answer quality and latency with your existing models before relying on it.
