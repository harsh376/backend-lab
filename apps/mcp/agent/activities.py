from collections.abc import Awaitable, Callable
from dataclasses import asdict

from temporalio import activity

from apps.mcp.agent.models import (
    AnswerRequest,
    AnswerResult,
    Passage,
    SynthesisInput,
)
from apps.mcp.telemetry import observation
from backend.services.kilt.kilt import KiltService


async def aextractive_synthesis(data: SynthesisInput) -> AnswerResult:
    """Fake-provider baseline: quote evidence, without claiming verification."""
    if not data.passages:
        return AnswerResult(
            short_answer="",
            explanation="No evidence was retrieved for this question.",
            abstained=True,
        )
    passage = data.passages[0]
    return AnswerResult(
        short_answer=passage.text,
        explanation=("Extractive baseline: the top passage is quoted verbatim."),
        citations=[passage],
    )


class AnswerActivities:
    def __init__(
        self,
        kilt: KiltService,
        synthesize: Callable[
            [SynthesisInput], Awaitable[AnswerResult]
        ] = aextractive_synthesis,
    ):
        self.kilt = kilt
        self.synthesize = synthesize

    @activity.defn(name="retrieve_answer_evidence")
    async def aretrieve(self, request: AnswerRequest) -> list[Passage]:
        request.validate()
        with observation(
            "retrieve_answer_evidence",
            input={"question": request.question, "limit": request.limit},
            trace_context=request.trace_context,
            metadata=_activity_metadata(),
            as_type="retriever",
        ) as span:
            passages = await self.kilt.aretrieve_passages(
                request.question, request.limit
            )
            if span:
                span.update(
                    output={
                        "passages": [
                            {k: p[k] for k in ("passage_id", "corpus_version")}
                            for p in passages
                        ]
                    }
                )
            return [Passage(**item) for item in passages]

    @activity.defn(name="synthesize_answer")
    async def agenerate(self, data: SynthesisInput) -> AnswerResult:
        with observation(
            "synthesize_answer",
            input={
                "question": data.question,
                "passages": [asdict(p) for p in data.passages],
            },
            trace_context=data.trace_context,
            metadata=_activity_metadata(),
        ) as span:
            result = await self._generate(data)
            if span:
                span.update(
                    output={
                        "abstained": result.abstained,
                        "provider": result.provider,
                        "citation_ids": [p.passage_id for p in result.citations],
                    }
                )
            return result

    async def _generate(self, data: SynthesisInput) -> AnswerResult:
        result = await self.synthesize(data)
        evidence = {p.passage_id: p for p in data.passages}
        # This checks citation identity, not semantic support. A real provider
        # must add evidence verification before claiming a supported answer.
        if result.abstained:
            return AnswerResult(
                "", result.explanation, abstained=True, provider=result.provider
            )
        if (
            not result.short_answer.strip()
            or not result.citations
            or any(evidence.get(p.passage_id) != p for p in result.citations)
        ):
            return AnswerResult(
                "",
                "Synthesis did not return valid retrieved citations.",
                abstained=True,
                provider=result.provider,
            )
        return result


def _activity_metadata() -> dict:
    if not activity.in_activity():
        return {}
    info = activity.info()
    return {
        "answer_id": info.workflow_id,
        "temporal_run_id": info.workflow_run_id,
        "activity_id": info.activity_id,
        "attempt": info.attempt,
    }
