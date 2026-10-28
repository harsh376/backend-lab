# Retrieval baseline

`retrieval-smoke-002.json` records the completed baseline run, including per-case
scores and trace IDs. Full ranked candidates and case snapshots remain in the
linked Temporal/Langfuse experiment.

- Experiment: `retrieval-smoke-002`
- Run ID: `kilt-eval-retrieval-5b02c301-d3b3-40b7-b24d-a8f8e2f3ce9f`
- Selection: all local `page_verified` cases, excluding `rejected` cases
- Retrieval limit: 100; corpus: `kilt`
- Query: Elasticsearch `multi_match` with default `best_fields` scoring and
  fields `wikipedia_title^3` and `text`, using the existing field analyzers
- Coverage: 45 completed, zero failed; all 45 scored at every cutoff

| Metric | Baseline |
| --- | ---: |
| Recall@5 | 0.5111111111111111 |
| Recall@10 | 0.5555555555555556 |
| Recall@50 | 0.6111111111111112 |
| Recall@100 | 0.6333333333333333 |

A direct rerun of the baseline query against the live corpus reproduced these
four averages exactly. Retrieval optimization is deferred. For future comparisons,
use the same case IDs, reference evidence, corpus contents, retrieval limit, and
scored coverage. The corpus name alone does not guarantee identical contents.

To rerun through MCP:

```json
{"limit": null, "retrieval_limit": 100, "experiment_name": "retrieval-baseline-repeat"}
```

Pass these arguments to `answers.run_retrieval_evals`, then poll
`answers.get_evals` with the returned run ID until completion.
