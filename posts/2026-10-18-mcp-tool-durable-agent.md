# MCP tool over a durable agent

Date: 2026-10-18

Code: [mcp-tool-durable-agent-v1](https://github.com/harsh376/backend-lab/tree/mcp-tool-durable-agent-v1)

## What I built

```
Codex -> MCP -> Temporal workflow -> Search Elasticsearch -> Synthesis -> Verification -> Response
```

- Ingested [KILT Knowledge source](https://github.com/facebookresearch/KILT) into
local Elasticsearch cluster. Snapshot of wikipedia pages.
- Implemented a RAG Agent as a starting point for context retrieval and answer synthesis.
- E2E Tracing
  - Instrumented OTEL and forwarded MCP traces to Cloud Langfuse. Separate traces for each tool call.
  - Captures token usage, cost in USD
- Enforcement of cost budget constraints
  - User is able to provide cost budget (USD) and the framework ensures we track committed cost and don't exceed
  the provided budget
- Used Temporal to manage workflow and background work
- Used Docker compose files for local development
- Added ability to use models provided by OpenAI, Claude, and local models via Ollama.

## Why I approached it this way

- Used KILT Knowledge Source because it comes with labeled data that can be used for evaluation. This project doesn't aim to be an agent on top of current Wikipedia. It is a bench to test and measure different approaches. And so having already available labeled data helps
- Used Temporal because it provides durable workers. I see durability as an essential quality for agentic work.
- Used Langfuse for tracing. It is OTEL compatible and has an easy-to-understand interface.
- Used Docker compose for development. All services are dockerized, compose makes it fairly easy to spin up the stack.


## What I learned

- Took some time getting used to Temporal's durability guarantees - workflow code is durable during replays, activity code is recoverable through retries
- Was cool to reproduce random worker failures and track the durable recovery through temporal UI and Langfuse spans


## What I’d try next

- Implement an Evaluation framework that establishes a baseline
- Implement MCP authorization
