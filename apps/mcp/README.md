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
