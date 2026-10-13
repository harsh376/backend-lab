import asyncio
import os

from elasticsearch import AsyncElasticsearch
from temporalio.client import Client
from temporalio.worker import Worker

from apps.api.services.kilt.kilt import KiltService
from apps.mcp.agent.activities import AnswerActivities
from apps.mcp.agent.workflow import AnswerWorkflow

TASK_QUEUE = "kilt-answers"


async def main() -> None:
    client = await Client.connect(os.getenv("TEMPORAL_ADDRESS", "localhost:7233"))
    es_url = os.getenv("ELASTICSEARCH_URL", "http://localhost:9200")
    async with AsyncElasticsearch(es_url) as es:
        activities = AnswerActivities(KiltService(es, os.getenv("KILT_INDEX", "kilt")))
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
