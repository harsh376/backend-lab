import asyncio

from elasticsearch import AsyncElasticsearch
from temporalio.client import Client
from temporalio.worker import Worker

from apps.mcp.agent.activities import AnswerActivities
from apps.mcp.agent.workflow import AnswerWorkflow
from apps.mcp.config import Settings
from backend.services.kilt.kilt import KiltService

TASK_QUEUE = "kilt-answers"


async def main() -> None:
    settings = Settings()
    client = await Client.connect(settings.temporal_address)
    async with AsyncElasticsearch(settings.elasticsearch_url) as es:
        activities = AnswerActivities(KiltService(es, settings.kilt_index))
        worker = Worker(
            client,
            task_queue=TASK_QUEUE,
            workflows=[AnswerWorkflow],
            activities=[activities.aretrieve, activities.agenerate],
            # Activities are coroutines on the event loop, so bound them here
            # rather than by a thread pool size.
            max_concurrent_activities=8,
        )
        await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
