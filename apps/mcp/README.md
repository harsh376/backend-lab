# Evidence-Backed Answers

See [the one-pager](ONE_PAGER.md) for the project scope.

## Serve local model if needed

```shell
ollama run qwen3.8
```

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

## Per-answer model budget

Supply an optional positive `budget_usd` when starting a run:

```json
{"question": "When did Arthur's Magazine begin publication?", "limit": 5, "budget_usd": 0.05}
```

Before synthesis and verification, a pricing activity estimates the call using
UTF-8 input bytes, the response schema, a framing allowance and the configured
maximum output tokens. The quote is saved in Temporal history before dispatch.
The model client checks that its model, output limit and estimated price still
fit that reservation before calling the provider. Pricing must be available in
LiteLLM's catalog; unavailable pricing causes abstention before dispatch.

On completion, reported model cost replaces the reservation, freeing unused
funds for verification. If verification cannot fit, the run abstains rather than
returning an unchecked answer. `result.budget` contains the limit, per-stage
reservations, usage-based costs, statuses and any stop reason. A call that
exceeds its reservation is marked `reservation_overrun`; spending above the run
limit is reported in `overrun_usd`. A known usage cost does not itself stop the
run: the next reservation must fit the remaining budget. If the final
verification succeeds but overruns, the verified answer is returned with the
overrun reported.

Budgeted model activities run with one attempt. A timeout or worker interruption
with an unknown provider outcome retains the reservation as unresolved and stops
further calls. Missing cost data does the same. A late provider completion can
still incur a charge: reservations are conservative estimates, not guaranteed
provider billing caps. Costs are based on LiteLLM pricing rather than invoices.
This budget covers server-side model calls, excluding infrastructure and host
assistant spend. Limits are independent per run, with no shared account budget.
Omitting `budget_usd` preserves the existing behavior and retry policy.

The final `record_answer_result` span includes `total_cost_usd`, the sum of known
synthesis and verification usage costs, with or without a budget. Unknown costs
do not erase known spend; the total is partial when a stage's cost is unknown.
It is null only when no usage costs are known.
Skipped verification contributes no cost. The optional `budget` output retains
committed spend (including unresolved reservations) separately from actual cost.

The workflow uses an async `budget_stage` context manager around each model
activity. Entry quotes and reserves; normal exit reconciles the recorded usage
cost; an activity failure retains the reservation and stops the run.
`reserved_cost_usd` names the pre-call estimate. `usage_cost_usd` names the cost
calculated from reported usage and catalog prices, rather than an invoice charge.

Budgeted and unlimited runs share the same workflow activity sequence. With no
budget supplied, the budget scopes skip quoting and accounting; model activities
retain their existing three-attempt retry policy.
