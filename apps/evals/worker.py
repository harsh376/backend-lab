"""Run with python -m apps.evals.worker."""

import asyncio

from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.worker import Worker

from apps.evals.activities import evaluate_mcp_case, load_eval_cases
from apps.evals.workflow import TASK_QUEUE, EvalWorkflow
from apps.mcp.telemetry import client as telemetry_client
from backend.config import Settings


async def main() -> None:
    client = await Client.connect(
        Settings().temporal_address, data_converter=pydantic_data_converter
    )
    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[EvalWorkflow],
        activities=[load_eval_cases, evaluate_mcp_case],
    )
    try:
        await worker.run()
    finally:
        telemetry = telemetry_client()
        if telemetry is not None:
            await asyncio.to_thread(telemetry.flush)


if __name__ == "__main__":
    asyncio.run(main())
