from temporalio import activity
from temporalio.exceptions import ApplicationError

from apps.mcp.agent.models import (
    AnswerRequest,
    AnswerResult,
    ArticleEvidence,
    FinalAnswerInput,
    FinalAnswerOutput,
    FinalBudgetOutput,
    FinalSynthesisOutput,
    SynthesisInput,
)
from apps.mcp.telemetry import observe
from backend.budget import Reservation, current_reservation
from backend.llm import ModelProviderError
from backend.services.answer_synthesis.answer_synthesis import (
    AnswerSynthesisService,
    SynthesisResponse,
)
from backend.services.answer_verification.answer_verification import (
    AnswerVerificationService,
    VerificationInput,
    VerificationResponse,
)
from backend.services.kilt.kilt import KiltService


class AnswerActivities:
    def __init__(
        self,
        kilt_service: KiltService,
        synthesis_service: AnswerSynthesisService,
        verification_service: AnswerVerificationService | None = None,
    ):
        self.kilt_service = kilt_service
        self.synthesis_service = synthesis_service
        self.verification_service = verification_service

    @activity.defn(name="retrieve_answer_evidence")
    @observe(as_type="retriever")
    async def aretrieve(self, request: AnswerRequest) -> list[ArticleEvidence]:
        request.validate()
        return await self.kilt_service.asearch_evidences(
            request.question, request.limit
        )

    @activity.defn(name="quote_synthesis")
    @observe()
    async def aquote_synthesis(self, data: SynthesisInput) -> Reservation:
        adapter = self.synthesis_service.adapter
        return adapter.model.quote(adapter._build_messages(data), SynthesisResponse)

    @activity.defn(name="quote_verification")
    @observe()
    async def aquote_verification(self, data: VerificationInput) -> Reservation:
        adapter = self.verification_service.adapter
        return adapter.model.quote(adapter._build_messages(data), VerificationResponse)

    @activity.defn(name="synthesize_answer")
    @observe()
    async def agenerate(self, data: SynthesisInput) -> AnswerResult:
        token = current_reservation.set(data.reservation)
        try:
            return await self.synthesis_service.synthesize(data)
        except ModelProviderError as error:
            raise ApplicationError(
                str(error), type=error.error_type, non_retryable=True
            ) from None
        finally:
            current_reservation.reset(token)

    @activity.defn(name="verify_answer")
    @observe()
    async def averify(self, data: VerificationInput) -> AnswerResult:
        if self.verification_service is None:
            raise ApplicationError("Verifier is not configured.", non_retryable=True)
        token = current_reservation.set(data.reservation)
        try:
            return await self.verification_service.verify(data)
        except ModelProviderError as error:
            raise ApplicationError(
                str(error), type=error.error_type, non_retryable=True
            ) from None
        finally:
            current_reservation.reset(token)

    @activity.defn(name="record_answer_result")
    @observe()
    async def arecord_result(self, data: FinalAnswerInput) -> FinalAnswerOutput:
        answer = data.answer
        budget = answer.budget
        costs = [answer.usage_cost_usd]
        if answer.verification is not None:
            costs.append(answer.verification.usage_cost_usd)
        known_costs = [cost for cost in costs if cost is not None]
        total_cost_usd = sum(known_costs) if known_costs else None
        return FinalAnswerOutput(
            short_answer=answer.short_answer,
            explanation=answer.explanation,
            citations=answer.citations,
            abstained=answer.abstained,
            synthesis=FinalSynthesisOutput(
                provider=answer.provider,
                model=answer.model,
                usage=answer.usage,
                usage_cost_usd=answer.usage_cost_usd,
            ),
            verification=answer.verification,
            total_cost_usd=total_cost_usd,
            budget=(
                FinalBudgetOutput(
                    limit_usd=budget.limit_usd,
                    entries=budget.entries,
                    stop_reason=budget.stop_reason,
                    committed_usd=budget.committed_usd,
                    overrun_usd=budget.overrun_usd,
                )
                if budget is not None
                else None
            ),
        )
