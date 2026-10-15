from dataclasses import dataclass

# Re-export shared payloads to preserve the existing MCP import surface.
from backend.services.answer_synthesis.answer_synthesis import (
    AnswerResult,
    Passage,
    SynthesisInput,
)

__all__ = ["AnswerRequest", "AnswerResult", "Passage", "SynthesisInput"]


@dataclass
class AnswerRequest:
    question: str
    limit: int = 5
    trace_context: dict[str, str] | None = None
    session_id: str | None = None

    def validate(self) -> None:
        if not self.question.strip():
            raise ValueError("question must not be empty")
        if not 1 <= self.limit <= 10:
            raise ValueError("limit must be between 1 and 10")
