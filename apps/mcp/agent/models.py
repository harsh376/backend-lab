from dataclasses import dataclass, field


@dataclass
class AnswerRequest:
    question: str
    limit: int = 5

    def validate(self) -> None:
        if not self.question.strip():
            raise ValueError("question must not be empty")
        if not 1 <= self.limit <= 10:
            raise ValueError("limit must be between 1 and 10")


@dataclass
class Passage:
    passage_id: str
    corpus_version: str
    wikipedia_id: str
    paragraph_id: int
    title: str
    text: str


@dataclass
class SynthesisInput:
    question: str
    passages: list[Passage]


@dataclass
class AnswerResult:
    short_answer: str
    explanation: str
    citations: list[Passage] = field(default_factory=list)
    abstained: bool = False
    provider: str = "extractive-baseline"
