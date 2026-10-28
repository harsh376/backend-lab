"""Evaluation dataset schemas and execution response contracts."""

from enum import StrEnum
from typing import Any, Literal, NotRequired, TypedDict

from pydantic import BaseModel, ConfigDict, Field, model_validator

type RetrievalSummary = dict[str, float | int | None]


class AnswerSummary(TypedDict):
    correctness: float | None
    correctness_count: int


class EvalRunResponse(TypedDict):
    run_id: str
    status: str
    experiment_id: NotRequired[str]
    experiment_url: NotRequired[str]
    coverage: NotRequired[dict[str, int]]
    results: NotRequired[list[dict]]
    summary: NotRequired[AnswerSummary]
    retrieval_summary: NotRequired[RetrievalSummary]


class VerificationTag(StrEnum):
    """Capabilities established by structural checks against the local corpus."""

    PAGE_VERIFIED = "page_verified"
    PASSAGE_VERIFIED = "passage_verified"


class EvalSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["local", "langfuse"] = "local"
    dataset_id: str | None = Field(default=None, min_length=1)
    version: str | None = Field(default=None, min_length=1)
    dataset: str = Field(min_length=1)
    split: Literal["train", "dev", "test"]
    record_id: str = Field(min_length=1)
    filename: str = Field(min_length=1)
    original_output: Any


class Evidence(BaseModel):
    model_config = ConfigDict(extra="allow")

    wikipedia_id: str = Field(min_length=1)
    start_paragraph_id: int = Field(ge=0)
    end_paragraph_id: int = Field(ge=0)

    @model_validator(mode="after")
    def ordered_span(self):
        if self.end_paragraph_id < self.start_paragraph_id:
            raise ValueError("end_paragraph_id precedes start_paragraph_id")
        return self


class EvalCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    group_id: str = Field(min_length=1)
    question: str = Field(min_length=1, pattern=r"\S")
    source: EvalSource
    accepted_answers: list[str]
    answerable: bool
    evidence_sets: list[list[Evidence]]
    tags: list[str] = Field(
        default_factory=list,
        description=(
            "Task labels and independent verification capabilities. page_verified: "
            "all declared evidence pages resolve uniquely. passage_verified: all "
            "declared paragraph ranges and supplied character offsets are valid. "
            "Neither tag establishes semantic support. Missing tags mean capability "
            "has not been established. rejected excludes a case from evaluation."
        ),
    )

    @model_validator(mode="after")
    def check_gold(self):
        if self.answerable and not any(a.strip() for a in self.accepted_answers):
            raise ValueError("answerable cases require an accepted answer")
        if any(not evidence_set for evidence_set in self.evidence_sets):
            raise ValueError("evidence sets must not be empty")
        return self
