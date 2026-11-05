# Optimizing a RAG agent with evals

Date: 2026-11-05

Code: [rag-eval-optimizations-v1](https://github.com/harsh376/backend-lab/tree/rag-eval-optimizations-v1)

Previous post: [MCP tool over a durable agent](2026-10-19-mcp-tool-durable-agent.md)

## Constraints

- **A local model only:** `ollama_chat/qwen3.8` for answering, verification and
  judging. No frontier models. The goal is to see how far a small local model
  can go.
- **Latency is a first-class metric.** On qwen3.8, prefill runs at about
  480 tokens/s, so every token of context costs time:

```
qwen3.8 prompt size vs time (200 output tokens)

 2,700 tokens   ███████████                      11 s
 7,000 tokens   █████████████████████            21 s
11,250 tokens   ███████████████████████████████  31 s
                └─ prefill ~2 s per 1,000 tokens ─┘
```

## TL;DR

Better retrieval plus whole articles made qwen much more accurate, but far too
slow. Cutting the context made it fast again but starved it of evidence.
**Sizing the context to (12 paragraphs, 5000 tokens)** recovered part of the
loss at about 11 s per answer.

| # | Change | Type | Sub-system | Correctness | Mean answer time |
| --- | --- | --- | --- | ---: | ---: |
| 0 | Baseline | — | recall@10 55.6% | 0.333 (45) | 7.6 s |
| 1 | Better article retrieval | Prerequisite | recall@10 **80.0%** | | |
| 2 | Whole articles, top 10 | Too slow | passage_recall@10 0.788 | 0.59 (45) | ~160 s |
| 3 | Context (5, 2000) | Latency fix | passage_recall@10 0.303 | 0.394 (33) | 7.2 s |
| 4 | Judge at temperature 0 | Measurement fix | judge agreement 193 → 198 / 198 | 0.364 (33) | 8.2 s |
| 5 | **Context (12, 5000)** | **Gain** | passage_recall@10 **0.449** | **0.485** (33) | 10.6 s |
| 6 | Gold dataset review | Measurement fix | 9 amended, 4 rejected | 0.485 (33), 0.463 (41) | 11.6 s (41) |
| | *gpt-5.6-terra, whole articles* | *Frontier reference* | | *0.65 (45)* | *4.9 s* |

Context = (paragraphs, tokens) sent to the answer model. Case counts are in
brackets: 45 is the full set and 33 is the passage-verified subset. Steps 4 and
6 changed the scores without changing the system. The frontier run cost $5.27
for 45 cases.

## Eval setup

### Dataset

```
KILT dev: NQ + HotpotQA
  └─ sample 30 NQ + 15 HotpotQA (seed 42) ──────── 45 cases
       └─ gold pages found in corpus ──────────── 45  page_verified
            └─ gold paragraphs match corpus ───── 33  passage_verified  ← most comparisons
```

Each case has a question, accepted answers, and gold evidence (page IDs and
paragraph ranges). Saved in `apps/evals/datasets/kilt-v1/dev.json`.

### Harness

```
Codex (MCP)
  │
  ├─ run_evals ───────────► ┌─ Temporal, eval worker pool ───────────────────────┐
  │                         │ load cases ─► AnswerWorkflow (production) ─► judge │
  ├─ run_retrieval_evals ─► │ load cases ─► retriever + paragraph selection      │
  │                         └────────────────────────┬───────────────────────────┘
  └─ get_evals ◄─ results                            ├─► Langfuse experiment
                                                     │   (trace per case, cost, commit, dataset hash)
                                                     └─► baselines saved to apps/evals/reports/
```

Evals run the same code as production, on their own Temporal worker pool.

### Error-analysis loop

```
run_evals ──► failing cases ──► create_dataset_from_eval ──► Langfuse dataset
    ▲                                                              │
    └──────────── run_evals(hosted_dataset=...) after a fix ◄──────┘
```

### Metrics

```
question ─► retrieve articles ─► select paragraphs ─► synthesize + verify ─► judge vs gold
                  ▲                     ▲                       ▲                  ▲
              recall@K           passage_recall@K          answer time        correctness
           (gold pages in       (gold paragraphs the      (per case,         (0/1, LLM judge)
              top K)             model actually sees)      before judge)
           no model calls         no model calls
```

Correctness and answer time decide whether a change helped. The recall metrics
are cheap diagnostics that show *where* evidence was lost.

## Changes

0. **Baseline**: original `best_fields` retrieval, top 5 articles, naive
   paragraph context. Error analysis showed the model often didn't get the
   evidence. (An earlier run of the same system scored 0.32.)
1. **Better article retrieval**: `cross_fields` BM25, one-hop link expansion,
   passage rerank and rank fusion (RRF). No model calls; retrieval went from
   about 54 ms to 135 ms.
2. **Whole articles, top 10:** about 500 paragraphs per question. Accurate but
   unusable on qwen. The same setup on gpt-5.6-terra is the frontier reference.
   Neither run's results were saved, so these numbers come from run notes.
3. **Compact context (5, 2000)**: rank paragraphs across articles and send only
   the top 5. Fast, but passage recall showed that in 15 of the 28
   cases with the right article, every gold paragraph was dropped.
4. **Judge at temperature 0**: measurement fix. The judge now agrees with hand
   labels on 198/198 judgments, up from 193/198.
5. **Context (12, 5000)**: chosen from a model-free sweep; each larger setting
   bought less recall for more time. Same code and judge as
   step 4, so the only difference is context size.
6. **Gold dataset review**: measurement fix. 32 keep, 9 amend (e.g. Army–Navy:
   gold 2017, corpus 2018), 4 reject.

## Learnings

- **With a local model, latency limits context.** Whole articles gave the best
  qwen accuracy, but not at a usable speed. The design question became how much
  evidence fits in a time budget.
- **Measure what the model sees.** Article recall looked good while the model
  was missing the evidence. Passage recall on the synthesis input found the
  bottleneck.
- **Separate gains from measurement fixes.** Steps 4 and 6 moved scores without
  changing the system.
- **Variance is now the limit.** Identical runs differ by about ±3 cases, and
  there's no holdout yet.
