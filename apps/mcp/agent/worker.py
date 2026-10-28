import asyncio

from elasticsearch import AsyncElasticsearch
from temporalio.client import Client
from temporalio.worker import Worker

from apps.mcp.agent.activities import AnswerActivities
from apps.mcp.agent.workflow import AnswerWorkflow
from apps.mcp.telemetry import client as telemetry_client
from apps.mcp.telemetry import observation
from backend.config import Settings
from backend.repositories.kilt import ElasticsearchKiltRepository
from backend.services.answer_synthesis.answer_synthesis import (
    AnswerSynthesisService,
    LiteLLMSynthesis,
)
from backend.services.answer_verification.answer_verification import (
    AnswerVerificationService,
    LiteLLMVerification,
)
from backend.services.kilt.kilt import KiltService

TASK_QUEUE = "kilt-answers"


async def main() -> None:
    settings = Settings()
    client = await Client.connect(settings.temporal_address)
    async with AsyncElasticsearch(settings.elasticsearch_url) as es:
        activities = AnswerActivities(
            kilt_service=KiltService(
                ElasticsearchKiltRepository(es, settings.kilt_index)
            ),
            synthesis_service=AnswerSynthesisService(
                LiteLLMSynthesis(settings, observation_factory=observation)
            ),
            verification_service=AnswerVerificationService(
                LiteLLMVerification(settings, observation_factory=observation)
            ),
        )
        worker = Worker(
            client,
            task_queue=TASK_QUEUE,
            workflows=[AnswerWorkflow],
            activities=[
                activities.aretrieve,
                activities.agenerate,
                activities.averify,
                activities.aquote_synthesis,
                activities.aquote_verification,
                activities.arecord_result,
            ],
            # Activities are coroutines on the event loop, so bound them here
            # rather than by a thread pool size.
            max_concurrent_activities=8,
        )
        try:
            await worker.run()
        finally:
            telemetry = telemetry_client()
            if telemetry is not None:
                await asyncio.to_thread(telemetry.flush)


if __name__ == "__main__":
    asyncio.run(main())
