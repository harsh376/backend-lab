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

## Model-free retrieval ensemble: 80% recall@10

[`retrieval-at10-002`](https://us.cloud.langfuse.com/project/cmv8er3760322ad0gyvm1n67l/experiments/results?baseline=ebf0d7fa25905ad5b2f3741c67ff73b5)
measured the production implementation of a lexical and link-based retrieval
ensemble. No model calls, embeddings, new dependencies, or index changes are used.

1. Retrieve 100 candidates with the existing cross-field BM25 query, independently
   of whether the caller requests 10 or 100 results. Larger requested limits are
   still supported. The stopword-only fallback is retained.
2. Score paragraphs from the first three seed articles by question-term overlap
   divided by `1 + unique_word_count ** 0.3`. Each seed contributes its five most
   relevant paragraphs; only positive-overlap paragraphs contribute links.
3. Decode linked Wikipedia titles, aggregate paragraph scores weighted by inverse
   seed rank, and select up to 100 titles. Search those titles with the original
   query to recover related articles. Expansion is one hop, with no recursion.
4. Rerank the union using local passage BM25 (`k1=1.2`, `b=0.75`). Windows contain
   120 non-stopword tokens, advancing by 80 tokens within each original paragraph;
   the title is included three times for context. Each article takes its best
   passage score. Statistics come only from the candidate passages.
5. Fuse the article, linked-article, and passage rankings with equal-weight
   reciprocal rank fusion (`k=10`), deduplicate Wikipedia IDs, and return the
   requested prefix. Search hit `score` is now the fused ranking score.

Local tokenization folds accents and removes question framing. It operates on
copies for scoring, preserving original paragraphs and citation offsets. Local
scoring runs in threads to avoid blocking the async worker loop. A normal query
with useful links makes two Elasticsearch searches and considers at most 200
articles for a requested limit of 100 or less. Missing anchors skip expansion.

`retrieval-at10-002-trials.json` records the comparison summaries, including
unsuccessful field-weight, term-coverage, and fuzzy-search variants. Field-weight
changes alone reduced recall@10; links and passage ranking provided complementary
gains. These trials used references only for evaluation, not candidate generation
or ranking. The selected code is in `backend/repositories/kilt_ranking.py` and
`backend/repositories/kilt.py`.

| Metric | Previous (`at10-001`) | Ensemble (`at10-002`) |
| --- | ---: | ---: |
| Recall@5 | 60.00% | 75.56% |
| Recall@10 | 67.78% | **80.00%** |
| Recall@50 | 78.89% | 85.56% |
| Recall@100 | 80.00% | 85.56% |

All 45 cases completed and were scored at every cutoff, with no failures or skips.
The full case snapshots matched the previous run exactly; dataset SHA-256 remains
`f37abbe8dfd9962907b5848a28b6b025567a7169c17d029cdbcd47db3690f89e`.
At recall@10, seven cases improved, none regressed, and 38 were unchanged.
`retrieval-at10-002.json` records per-case changes, scores, source hashes, and traces.

| Retrieval latency | Previous | Ensemble |
| --- | ---: | ---: |
| Mean | 54 ms | 148 ms |
| Median | 54 ms | 135 ms |
| p95 | 76 ms | 227 ms |

These timings are observations from sequential local eval runs, not a controlled
load benchmark. The extra search and passage scoring trade latency and CPU for
recall. As with the previous change, the 45-case set was used to select the method;
80% is a development-set result and has not been validated on an independent
holdout. The corpus was unchanged during comparison, but its name is not a
content fingerprint.

Validation: 113 targeted tests passed; Ruff lint and formatting checks passed.
Tests cover accent normalization, link decoding and bounds, paragraph relevance,
stable fusion and deduplication, fallback queries, citation preservation, and
consistent candidate pools across output limits. Both local workers were rebuilt
and restarted. To repeat, call `answers.run_retrieval_evals` with `limit=null`,
`retrieval_limit=100`, and a unique experiment name, then poll `answers.get_evals`.

## Synthesis context, passage ranking, and judge baselines (2026-10-29)

All runs use the 33 local `passage_verified` cases, corpus `kilt`, retrieval
limit 10 (the answer workflow's limit), and `ollama_chat/qwen3.8` for synthesis,
verification, and judging. Dataset SHA-256 remains
`f37abbe8dfd9962907b5848a28b6b025567a7169c17d029cdbcd47db3690f89e`.

### Passage recall on synthesis input

`passage_recall@K` now scores the paragraphs compact synthesis actually receives
(`prepare_input` over the top K articles), not whole retrieved articles.
`retrieval-synthesis-input-sweep-20261029.json` records five runs (summaries and
per-case scores). Retrieval was identical in every run (recall@5 0.727,
recall@10 0.788).

| Paragraphs / tokens | passage_recall@5 | passage_recall@10 | Paragraphs selected @10 |
| --- | ---: | ---: | ---: |
| 5 / 2000 | 0.333 | 0.303 | 5 |
| 8 / 3500 | 0.419 | 0.379 | 8 |
| 12 / 5000 | 0.525 | 0.449 | 12 |
| 20 / 8000 | 0.566 | 0.520 | 20 |
| full | 0.732 | 0.788 | ~568 (median 523) |

The paragraph cap bound every compact case. At 5/2000, 15 of the 28 cases whose
reference page was retrieved lost every reference paragraph during selection.
12/5000 became the default.

`retrieval-passage-ranker-bm25-20261029.json` is the retrieval baseline after
passage scoring moved behind `PassageRanker` (`bm25`). It reproduced the
12/5000 sweep run exactly for all 33 cases.

### Judge temperature

`judge-rejudge-20261029.json` re-judged 66 saved answers three times under each
condition and compared verdicts with hand labels (strict specificity: a year does
not match a full-date reference).

| Judge | Agreement with labels | False correct / false incorrect | Answers with disagreeing samples |
| --- | ---: | ---: | ---: |
| v1, model default sampling (temperature 1) | 193 / 198 | 3 / 2 | 4 / 66 |
| v1, temperature 0 | 198 / 198 | 0 / 0 | 0 / 66 |
| candidate v2 prompt, temperature 0 | 198 / 198 | 0 / 0 | 0 / 66 |

Temperature alone removed the judge noise, so the judge now runs at
`EVAL_JUDGE_TEMPERATURE=0` with the unchanged `answer-correctness-v1` prompt.
Labels are one reviewer's; three ambiguous labels are listed in the file.

### Answer baselines

Both runs used commit `bca5553` (clean tree), verification enabled, and the
temperature-0 judge. Each file includes `baseline_configuration`.

| Context | Correctness | Answered | Correct / answered | Median case time |
| --- | ---: | ---: | ---: | ---: |
| 12 / 5000 (`answer-passage-verified-p12-t5000-judge-t0-20261029.json`) | **0.485** (16/33) | 21 | 76% | 10.5 s |
| 5 / 2000 (`answer-passage-verified-p5-t2000-judge-t0-20261029.json`) | 0.364 (12/33) | 15 | 80% | 6.4 s |

12/5000 answered four cases correctly that 5/2000 did not, and none the other way.
Synthesis and verification still sample at the model default: against same-day
runs with the earlier judge, outcomes changed on 7 (12/5000) and 4 (5/2000) of
33 cases, so expect about ±2–3 cases between runs. Correctness from earlier
reports was judged at the model default and is not directly comparable.

Of the five answered-but-incorrect cases at 12/5000, two have gold answers that
disagree with the corpus snapshot (Army–Navy 2018 vs 2017; first
Governor-General), one is a year for a full-date reference (Clifford), and two
need a second-hop article that was not retrieved (Stokely Webster, Gualeguaychú).

## Dataset review baselines (2026-11-04)

The KILT dev set now has the [review](../datasets/kilt-v1/README.md#review)
applied: 32 keep, 9 amend, 4 reject. All 33 `passage_verified` cases remain
eligible, but 8 of them have amended gold answers or evidence, so scores from
before this section are not directly comparable. These runs applied the review
from a separate overlay file (recorded `dataset_version`
`c5c0bdb5b415d68be364d537a597cd61f60e8da05ec5798d203e751fe8ff08c0`). The review
was then merged into `dev.json` with identical cases; its SHA-256 is now
`bdc9400de1c74937a3a32500466e0e61b0d2767d7c8430ad52a15fd49e6bebaa`.

Both runs used the 33 `passage_verified` cases, retrieval limit 10, and the
2026-10-29 settings (compact 12/5000, `bm25` passage ranker, verification
enabled, temperature-0 judge), on commit `4875e53` plus the uncommitted review
changes. Each file includes `baseline_configuration`.

| Run | Before review (10-29) | After review |
| --- | ---: | ---: |
| `passage_recall@5` (`retrieval-passage-verified-reviewed-20261104.json`) | 0.525 | 0.556 |
| `passage_recall@10` | 0.449 | 0.480 |
| recall@10 | 0.788 | 0.788 |
| Correctness (`answer-passage-verified-p12-t5000-reviewed-20261104.json`) | 0.485 (16/33) | 0.485 (16/33) |
| Answered / correct of answered | 21 / 76% | 20 / 80% |
| Median case time | 10.5 s | 10.5 s |

The whole passage-recall gain is Army–Navy, whose gold evidence now points at the
paragraph containing the answer. Retrieval itself did not change.

In the answer run the Challengers case hit the activity StartToClose timeout; it
was re-run alone and merged (`reruns` in the configuration). It abstained.

The unchanged correctness hides opposite moves. Army–Navy became correct purely
from the gold fix (the same answer, "December 8, 2018", was wrong on 10-29). The
other changes are synthesis variance on cases whose gold did not change: Astros and
end of World War II in the Pacific abstained after being correct, Shadows over
Camelot became correct, and the first Governor-General abstained after answering
"Lord William Bentinck", which the reviewed gold now accepts. Synthesis variance
is now the main source of noise between runs.

Of the four answered-but-incorrect cases, Clifford gives a year for a full-date
reference, Olympics returned an unflagged "excerpts do not contain" answer, and
Stokely Webster and Gualeguaychú need a second-hop article that was not retrieved.

### Full reviewed set

`answer-all-p12-t5000-reviewed-20261105.json` runs every eligible case (41: all
cases except the 4 rejected) with the same settings and dataset version as the
33-case run above. No case timed out.

| Cases | Correctness | Answered | Median case time |
| --- | ---: | ---: | ---: |
| All 41 | **0.463** (19/41) | 23 | 11.2 s |
| 33 `passage_verified` | 0.515 (17/33) | 20 | |
| 8 without `passage_verified` | 0.250 (2/8) | 3 | |

On the 33 `passage_verified` cases this run scored 17/33 against 16/33 the day
before, with five cases changing outcome in opposite directions. First
Governor-General (now "Lord William Bentinck"), Astros, and end of World War II in
the Pacific became correct; Puerto Rico and Shadows over Camelot abstained after
being correct. Two runs of identical settings therefore differ by about ±3 cases
(±0.09), larger than most configuration effects measured so far.

The 8 cases without `passage_verified` mostly abstain (5 of 8). Kubo answered
"September 9, 2016", which the corpus article does not contain; the reference is
the US release date, August 19, 2016.
