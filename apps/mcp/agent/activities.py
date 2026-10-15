from temporalio import activity
from temporalio.exceptions import ApplicationError

from apps.mcp.agent.models import AnswerRequest, AnswerResult, Passage, SynthesisInput
from apps.mcp.telemetry import observe
from backend.llm import ModelProviderError
from backend.services.answer_synthesis.answer_synthesis import (
    AnswerSynthesisService,
)
from backend.services.answer_verification.answer_verification import (
    AnswerVerificationService,
    VerificationInput,
)
from backend.services.kilt.kilt import KiltService


class AnswerActivities:
    def __init__(
        self,
        kilt: KiltService,
        synthesis: AnswerSynthesisService,
        verification: AnswerVerificationService | None = None,
    ):
        self.kilt = kilt
        self.synthesis = synthesis
        self.verification = verification

    @activity.defn(name="retrieve_answer_evidence")
    @observe(as_type="retriever")
    async def aretrieve(self, request: AnswerRequest) -> list[Passage]:
        request.validate()
        passages = await self.kilt.aretrieve_passages(request.question, request.limit)
        return [Passage(**item) for item in passages]

    @activity.defn(name="synthesize_answer")
    @observe()
    async def agenerate(self, data: SynthesisInput) -> AnswerResult:
        try:
            return await self.synthesis.synthesize(data)
        except ModelProviderError as error:
            raise ApplicationError(
                str(error), type=error.error_type, non_retryable=True
            ) from None

    @activity.defn(name="verify_answer")
    @observe()
    async def averify(self, data: VerificationInput) -> AnswerResult:
        if self.verification is None:
            raise ApplicationError("Verifier is not configured.", non_retryable=True)
        try:
            return await self.verification.verify(data)
        except ModelProviderError as error:
            raise ApplicationError(
                str(error), type=error.error_type, non_retryable=True
            ) from None
