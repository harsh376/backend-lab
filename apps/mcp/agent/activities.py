from collections.abc import Awaitable, Callable

from temporalio import activity

from apps.api.services.kilt.kilt import KiltService
from apps.mcp.agent.models import (
    AnswerRequest,
    AnswerResult,
    Passage,
    SynthesisInput,
)


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
        passages = await self.kilt.aretrieve_passages(request.question, request.limit)
        return [Passage(**item) for item in passages]

    @activity.defn(name="synthesize_answer")
    async def agenerate(self, data: SynthesisInput) -> AnswerResult:
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
