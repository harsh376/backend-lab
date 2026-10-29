import math
from dataclasses import dataclass, field

from backend.budget import BudgetEntry

# Re-export shared payloads to preserve the existing MCP import surface.
from backend.services.answer_synthesis.answer_synthesis import (
    AnswerResult,
    ArticleCandidates,
    ArticleEvidence,
    Paragraph,
    SynthesisInput,
    VerificationResult,
)
from backend.services.answer_verification.answer_verification import VerificationInput

__all__ = [
    "AnswerRequest",
    "AnswerResult",
    "ArticleCandidates",
    "ArticleEvidence",
    "FinalAnswerInput",
    "FinalAnswerOutput",
    "Paragraph",
    "SynthesisInput",
    "VerificationInput",
]


@dataclass
class AnswerRequest:
    question: str
    limit: int = 10
    trace_context: dict[str, str] | None = None
    session_id: str | None = None

    budget_usd: float | None = None
    timeout_settings: dict[str, float | int] | None = None
    verification_enabled: bool = True

    def validate(self) -> None:
        if self.budget_usd is not None and (
            not math.isfinite(self.budget_usd) or self.budget_usd <= 0
        ):
            raise ValueError("budget_usd must be finite and positive")
        if not self.question.strip():
            raise ValueError("question must not be empty")
        if not 1 <= self.limit <= 100:
            raise ValueError("limit must be between 1 and 100")


@dataclass
class FinalBudgetOutput:
    limit_usd: float
    entries: list[BudgetEntry]
    stop_reason: str | None
    committed_usd: float
    overrun_usd: float


@dataclass
class FinalSynthesisOutput:
    provider: str = "litellm"
    model: str | None = None
    usage: dict[str, int] = field(default_factory=dict)
    usage_cost_usd: float | None = None


@dataclass
class FinalAnswerOutput:
    short_answer: str
    explanation: str
    citations: list[Paragraph] = field(default_factory=list)
    abstained: bool = False
    synthesis: FinalSynthesisOutput = field(default_factory=FinalSynthesisOutput)
    verification: VerificationResult | None = None
    budget: FinalBudgetOutput | None = None
    total_cost_usd: float | None = None


@dataclass
class FinalAnswerInput:
    answer: AnswerResult
    trace_context: dict[str, str] | None = None
    session_id: str | None = None
