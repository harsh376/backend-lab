"""Page recall over retrieved candidates; passage recall over synthesis input."""

from apps.evals.models import EvalCase, RetrievalSummary, VerificationTag

RECALL_KS = (5, 10, 50, 100)
RETRIEVAL_METRICS = tuple(
    f"{prefix}@{k}" for prefix in ("recall", "passage_recall") for k in RECALL_KS
)


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


def passage_recall(
    case: EvalCase, synthesis_passages: set[tuple[str, int]]
) -> float | None:
    """Best distinct paragraph recall over the prepared synthesis input.

    Passages are (Wikipedia page ID, paragraph offset) pairs the synthesis model
    receives. Reference spans are inclusive; overlapping spans and repeated
    references count only once.
    """
    if (
        not case.answerable
        or not case.evidence_sets
        or VerificationTag.PASSAGE_VERIFIED not in case.tags
    ):
        return None
    return max(
        len(passages & synthesis_passages) / len(passages)
        for evidence_set in case.evidence_sets
        if (
            passages := {
                (e.wikipedia_id, paragraph)
                for e in evidence_set
                for paragraph in range(e.start_paragraph_id, e.end_paragraph_id + 1)
            }
        )
    )


def evaluate_retrieval(
    case: EvalCase,
    candidates: dict | None,
    synthesis_passages: dict[int, set[tuple[str, int]]] | None = None,
) -> dict:
    """Score page recall on retrieved candidates and passage recall on the
    synthesis input prepared from the top-k candidates."""
    result = {
        "version": "synthesis-input-passage-recall-v4",
        "stage": "article_candidates",
        "passage_stage": "synthesis_input",
        "ks": list(RECALL_KS),
        **{metric: None for metric in RETRIEVAL_METRICS},
    }
    if not case.answerable or not case.evidence_sets:
        return {**result, "reason": "No applicable reference evidence."}
    if candidates is None:
        return {**result, "reason": "Retrieval run did not expose article candidates."}
    page_ids = candidates["ranked_page_ids"]
    limit = candidates["limit"]
    scored_ks = [k for k in RECALL_KS if k <= limit]
    return {
        **result,
        "corpus_version": candidates["corpus_version"],
        "ranked_page_ids": page_ids,
        "candidate_limit": limit,
        "scored_ks": scored_ks,
        **{f"recall@{k}": recall_at_k(case, page_ids, k) for k in scored_ks},
        **{
            f"passage_recall@{k}": passage_recall(case, synthesis_passages[k])
            for k in scored_ks
            if synthesis_passages is not None
        },
        "synthesis_paragraph_counts": (
            {str(k): len(synthesis_passages[k]) for k in scored_ks}
            if synthesis_passages is not None
            else None
        ),
        "passage_recall_reason": (
            "Reference paragraph ranges have not been passage-verified."
            if VerificationTag.PASSAGE_VERIFIED not in case.tags
            else "Retrieval run did not expose synthesis input."
            if synthesis_passages is None
            else None
        ),
    }


def summarize_retrieval(results: list[dict]) -> RetrievalSummary:
    summary = {}
    for metric in RETRIEVAL_METRICS:
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
