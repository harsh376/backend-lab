"""Article-candidate recall, independent of synthesis and paragraph selection."""

from apps.evals.models import EvalCase, RetrievalSummary

RECALL_KS = (5, 10, 50, 100)


def recall_at_k(case: EvalCase, ranked_page_ids: list[str], k: int) -> float | None:
    """Best page recall over alternative evidence sets; repeated pages count once."""
    if k < 1:
        raise ValueError("k must be positive")
    if not case.answerable or not case.evidence_sets:
        return None
    retrieved = set(ranked_page_ids[:k])
    return max(
        len(retrieved & pages) / len(pages)
        for evidence_set in case.evidence_sets
        if (pages := {e.wikipedia_id for e in evidence_set})
    )


def evaluate_retrieval(case: EvalCase, candidates: dict | None) -> dict:
    """Score ranked candidates returned by the production retriever."""
    result = {
        "version": "article-recall-v2",
        "stage": "article_candidates",
        "ks": list(RECALL_KS),
        **{f"recall@{k}": None for k in RECALL_KS},
    }
    if not case.answerable or not case.evidence_sets:
        return {**result, "reason": "No applicable reference evidence."}
    if candidates is None:
        return {**result, "reason": "Retrieval run did not expose article candidates."}
    page_ids = candidates["ranked_page_ids"]
    limit = candidates["limit"]
    return {
        **result,
        "corpus_version": candidates["corpus_version"],
        "ranked_page_ids": page_ids,
        "candidate_limit": limit,
        "scored_ks": [k for k in RECALL_KS if k <= limit],
        **{
            f"recall@{k}": recall_at_k(case, page_ids, k)
            for k in RECALL_KS
            if k <= limit
        },
    }


def summarize_retrieval(results: list[dict]) -> RetrievalSummary:
    summary = {}
    for k in RECALL_KS:
        metric = f"recall@{k}"
        values = [
            value
            for result in results
            if (
                value := result.get("evaluators", {})
                .get("retrieval_recall_at_k", {})
                .get(metric)
            )
            is not None
        ]
        summary[metric] = sum(values) / len(values) if values else None
        summary[f"{metric}_count"] = len(values)
    return summary
