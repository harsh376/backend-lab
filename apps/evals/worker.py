"""Run with python -m apps.evals.worker."""

import asyncio

from elasticsearch import AsyncElasticsearch
from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.worker import Worker

from apps.evals.activities import (
    RetrievalEvalActivities,
    evaluate_mcp_case,
    load_eval_cases,
)
from apps.evals.workflow import TASK_QUEUE, EvalWorkflow
from apps.mcp.telemetry import client as telemetry_client
from backend.config import Settings
from backend.repositories.kilt import ElasticsearchKiltRepository
from backend.services.answer_synthesis.answer_synthesis import (
    create_synthesis_service,
)
from backend.services.kilt.kilt import KiltService


async def main() -> None:
    settings = Settings()
    client = await Client.connect(
        settings.temporal_address, data_converter=pydantic_data_converter
    )
    async with AsyncElasticsearch(settings.elasticsearch_url) as es:
        # Passage recall scores the input the answer worker's synthesis receives,
        # so context settings must match the answer worker's.
        retrieval = RetrievalEvalActivities(
            KiltService(ElasticsearchKiltRepository(es, settings.kilt_index)),
            create_synthesis_service(settings),
        )
        worker = Worker(
            client,
            task_queue=TASK_QUEUE,
            workflows=[EvalWorkflow],
            activities=[load_eval_cases, evaluate_mcp_case, retrieval.evaluate],
        )
        try:
            await worker.run()
        finally:
            telemetry = telemetry_client()
            if telemetry is not None:
                await asyncio.to_thread(telemetry.flush)


if __name__ == "__main__":
    asyncio.run(main())
