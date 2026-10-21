"""Binary page relevance: gold union, unique pages in first-seen rank order."""

from typing import NotRequired, TypedDict

from apps.evals.models import EvalCase, RetrievalSummary

type GoldPageIds = set[str]
type RankedPageIds = list[str]
type PageRanking = tuple[GoldPageIds, RankedPageIds] | None
type RankingReason = str


class RetrievalJudgment(TypedDict):
    k: int
    reason: NotRequired[str]


class MAPKResult(RetrievalJudgment):
    ap_at_k: float | None


class MRRKResult(RetrievalJudgment):
    reciprocal_rank_at_k: float | None


def _ranking(
    case: EvalCase, passages: list[dict] | None, k: int
) -> tuple[PageRanking, RankingReason]:
    if k <= 0:
        raise ValueError("k must be positive")
    if "page_verified" not in case.tags:
        return None, "Case is not page_verified."
    gold = {e.wikipedia_id for group in case.evidence_sets for e in group}
    if not gold:
        return None, "No gold evidence pages."
    if passages is None:
        return None, "Original retrieval output is unavailable."
    pages = list(dict.fromkeys(p["wikipedia_id"] for p in passages))[:k]
    return (gold, pages), ""


async def evaluate_mapk(
    case: EvalCase, passages: list[dict] | None, *, k: int = 5
) -> MAPKResult:
    """Per-case AP@k; mean these values across applicable cases for MAP@k."""
    ranking, reason = _ranking(case, passages, k)
    if ranking is None:
        return {"ap_at_k": None, "k": k, "reason": reason}
    gold, pages = ranking
    hits = 0
    total = 0.0
    for rank, page in enumerate(pages, 1):
        if page in gold:
            hits += 1
            total += hits / rank
    return {"ap_at_k": total / min(len(gold), k), "k": k}


async def evaluate_mrrk(
    case: EvalCase, passages: list[dict] | None, *, k: int = 5
) -> MRRKResult:
    """Per-case reciprocal rank@k; its mean is MRR@k."""
    ranking, reason = _ranking(case, passages, k)
    if ranking is None:
        return {"reciprocal_rank_at_k": None, "k": k, "reason": reason}
    gold, pages = ranking
    return {
        "reciprocal_rank_at_k": next(
            (1 / rank for rank, page in enumerate(pages, 1) if page in gold), 0.0
        ),
        "k": k,
    }


def summarize_retrieval(results: list[dict]) -> RetrievalSummary:
    def mean_metric(evaluator: str, metric: str) -> tuple[float | None, int]:
        judgments = [r.get("evaluators", {}).get(evaluator, {}) for r in results]
        values = [j[metric] for j in judgments if j.get(metric) is not None]
        return (sum(values) / len(values) if values else None), len(values)

    map_score, map_count = mean_metric("retrieval_mapk", "ap_at_k")
    mrr_score, mrr_count = mean_metric("retrieval_mrrk", "reciprocal_rank_at_k")
    return {
        "map_at_k": map_score,
        "map_at_k_count": map_count,
        "mrr_at_k": mrr_score,
        "mrr_at_k_count": mrr_count,
    }
