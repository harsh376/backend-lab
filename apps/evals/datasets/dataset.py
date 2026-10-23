"""Dataset loading, validation, and case selection shared by MCP and builders."""

import hashlib
import json
import re
from pathlib import Path

from apps.evals.models import EvalCase


def load_cases(path: Path) -> list[EvalCase]:
    try:
        records = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as error:
        raise ValueError(f"{path}: {error}") from error
    if not isinstance(records, list):
        raise ValueError(f"{path}: dataset must be a JSON array")
    cases = []
    seen = set()
    for index, record in enumerate(records):
        try:
            case = EvalCase.model_validate(record)
            if case.case_id in seen:
                raise ValueError(f"duplicate case_id: {case.case_id}")
        except ValueError as error:
            raise ValueError(f"{path}: record[{index}]: {error}") from error
        seen.add(case.case_id)
        cases.append(case)
    if not cases:
        raise ValueError(f"{path}: dataset is empty")
    return cases


def select_cases(
    cases: list[EvalCase],
    *,
    case_id: str | None = None,
    limit: int | None = 1,
    tags: list[str] | None = None,
) -> list[EvalCase]:
    """Select eligible cases in dataset order, requiring every requested tag."""
    if limit is not None and limit <= 0:
        raise ValueError("limit must be positive")
    selected = [
        case
        for case in cases
        if (case_id is None or case.case_id == case_id)
        and "rejected" not in case.tags
        and set(tags or ()).issubset(case.tags)
    ][:limit]
    if not selected:
        raise ValueError("No eligible cases match the requested case ID and tags")
    return selected


def question_group_id(question: str) -> str:
    """Group the same normalized question across dataset sources."""
    normalized = re.sub(r"\W+", " ", question.casefold()).strip()
    return "question-" + hashlib.sha256(normalized.encode()).hexdigest()[:16]
