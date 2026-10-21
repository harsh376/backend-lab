from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

from apps.mcp.agent.budget import BudgetStopped, budget_stage

with workflow.unsafe.imports_passed_through():
    from apps.mcp.agent.models import (
        AnswerRequest,
        AnswerResult,
        FinalAnswerInput,
        FinalAnswerOutput,
        Passage,
        SynthesisInput,
        VerificationInput,
    )
    from backend.budget import BudgetReport


@workflow.defn
class AnswerWorkflow:
    @workflow.run
    async def run(self, request: AnswerRequest) -> AnswerResult:
        request.validate()
        passages = await workflow.execute_activity(
            "retrieve_answer_evidence",
            request,
            result_type=list[Passage],
            start_to_close_timeout=timedelta(seconds=30),
            schedule_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        budget_report = (
            BudgetReport(request.budget_usd) if request.budget_usd is not None else None
        )
        model_retry_policy = RetryPolicy(maximum_attempts=1 if budget_report else 3)
        answer = AnswerResult("", "No evidence was retrieved.", abstained=True)
        if budget_report is not None and not passages:
            return await self._finish(answer, budget_report, request, passages)
        synthesis = SynthesisInput(
            request.question, passages, request.trace_context, request.session_id
        )
        try:
            async with budget_stage(budget_report, "synthesis", synthesis) as stage:
                answer = await workflow.execute_activity(
                    "synthesize_answer",
                    synthesis,
                    result_type=AnswerResult,
                    start_to_close_timeout=timedelta(seconds=60),
                    schedule_to_close_timeout=timedelta(minutes=3),
                    retry_policy=model_retry_policy,
                )
                stage.record_cost(answer.usage_cost_usd)
            if answer.abstained:
                return await self._finish(answer, budget_report, request, passages)

            verification = VerificationInput(
                request.question, answer, request.trace_context, request.session_id
            )
            async with budget_stage(
                budget_report, "verification", verification
            ) as stage:
                answer = await workflow.execute_activity(
                    "verify_answer",
                    verification,
                    result_type=AnswerResult,
                    start_to_close_timeout=timedelta(seconds=60),
                    schedule_to_close_timeout=timedelta(minutes=3),
                    retry_policy=model_retry_policy,
                )
                stage.record_cost(
                    answer.verification.usage_cost_usd if answer.verification else None
                )
        except BudgetStopped:
            pass
        return await self._finish(answer, budget_report, request, passages)

    async def _finish(
        self,
        answer: AnswerResult,
        budget_report: BudgetReport | None,
        request: AnswerRequest,
        passages: list[Passage],
    ) -> AnswerResult:
        answer.retrieved_passages = passages
        if budget_report is not None and budget_report.stop_reason:
            answer.short_answer = ""
            answer.citations = []
            answer.abstained = True
            answer.explanation = (
                "Budget enforcement stopped the run: " + budget_report.stop_reason
            )
        answer.budget = budget_report
        try:
            await workflow.execute_activity(
                "record_answer_result",
                FinalAnswerInput(answer, request.trace_context, request.session_id),
                result_type=FinalAnswerOutput,
                start_to_close_timeout=timedelta(seconds=10),
                schedule_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
        except ActivityError:
            workflow.logger.warning("Could not record the finalized answer trace span")
        return answer


if __name__ == "__main__":
    import asyncio
    import json
    from dataclasses import asdict
    from uuid import uuid4

    from temporalio.client import Client

    from backend.config import Settings

    async def main(question: str) -> None:
        client = await Client.connect(Settings().temporal_address)
        result = await client.execute_workflow(
            AnswerWorkflow.run,
            AnswerRequest(question),
            id=f"kilt-answer-{uuid4()}",
            task_queue="kilt-answers",
        )
        print(json.dumps(asdict(result), indent=2, ensure_ascii=False))

    asyncio.run(main("who wrote the song photograph by ringo starr"))
