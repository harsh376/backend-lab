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
four averages exactly. For future comparisons,
use the same case IDs, reference evidence, corpus contents, retrieval limit, and
scored coverage. The corpus name alone does not guarantee identical contents.

To rerun through MCP:

```json
{"limit": null, "retrieval_limit": 100, "experiment_name": "retrieval-baseline-repeat"}
```

Pass these arguments to `answers.run_retrieval_evals`, then poll
`answers.get_evals` with the returned run ID until completion.

## Recall@10 improvement

The production query now uses `multi_match` with `type=cross_fields` and
`analyzer=stop`, retaining the title boost and existing index. The shared analyzer
allows title and body terms to participate in the same cross-field scoring group;
their index analyzers otherwise differ. The built-in stop analyzer removes common
words without stemming terms that the existing index stores unstemmed.

If the query returns no hits, retrieval retries the original baseline query. This
preserves candidates for queries made entirely of stop words, such as
"To Be or Not to Be". The fallback was checked against the live corpus. A query
with no matches takes two searches; successful first queries take one.

The read-only query comparison in `retrieval-at10-query-comparison.json` reproduced
the baseline before evaluating these two alternatives:

| Query | Recall@10 |
| --- | ---: |
| Baseline | 55.56% |
| Shared stop analyzer, original best-fields scoring | 52.22% |
| Shared stop analyzer with cross-field scoring | 67.78% |

The selected change was then measured through `answers.run_retrieval_evals` as
[`retrieval-at10-001`](https://us.cloud.langfuse.com/project/cmv8er3760322ad0gyvm1n67l/experiments/results?baseline=3cbc2d3840485fe793291f5afe5904de).
The compact results are saved in `retrieval-at10-001.json`.

| Metric | Baseline | Improved | Change (percentage points) |
| --- | ---: | ---: | ---: |
| Recall@5 | 51.11% | 60.00% | +8.89 |
| Recall@10 | 55.56% | 67.78% | +12.22 |
| Recall@50 | 61.11% | 78.89% | +17.78 |
| Recall@100 | 63.33% | 80.00% | +16.67 |

Both runs completed and scored all 45 cases, with zero failures or skipped scores.
Case IDs and full case snapshots matched exactly. Both runs used corpus `kilt`
and retrieval limit 100. Dataset SHA-256:
`f37abbe8dfd9962907b5848a28b6b025567a7169c17d029cdbcd47db3690f89e`.

At recall@10, nine cases improved, two regressed, and 34 were unchanged. Regressions:

- `nq-dev--8491993331568056625`: "when did world war 2 end in the pacific",
  from 1.0 to 0.0.
- `hotpotqa-dev-5ab499a55542996a3a969f9f`: "Were Shadows Over Camelot and
  Battle Sheep released by the same publisher?", from 1.0 to 0.5.

This is a development-set improvement on 45 cases used to select the query;
generalization has not been measured on an independent holdout. Retrieval recall
does not measure final-answer correctness. The change requires no reindexing or
model calls. Both local eval and answer workers were rebuilt and restarted.

Validation: 105 targeted repository, service, retrieval-evaluator, eval workflow,
answer workflow, and MCP tests passed; Ruff lint and format checks passed.
