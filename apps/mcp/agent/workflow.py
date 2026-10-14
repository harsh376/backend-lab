from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from apps.mcp.agent.models import (
        AnswerRequest,
        AnswerResult,
        Passage,
        SynthesisInput,
    )


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
        return await workflow.execute_activity(
            "synthesize_answer",
            SynthesisInput(request.question, passages),
            result_type=AnswerResult,
            start_to_close_timeout=timedelta(seconds=60),
            schedule_to_close_timeout=timedelta(minutes=3),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )


if __name__ == "__main__":
    import asyncio
    import json
    from dataclasses import asdict
    from uuid import uuid4

    from temporalio.client import Client

    from apps.mcp.config import Settings

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
