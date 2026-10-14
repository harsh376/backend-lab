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
