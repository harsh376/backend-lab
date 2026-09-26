"""
Main thread
└── asyncio.run(main())          → Main event loop
    ├── Worker thread 1
    │   └── asyncio.run(run_jobs()) → Worker event loop
    └── Worker thread 2
        └── asyncio.run(run_jobs()) → Worker event loop
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor


async def async_job(job_id):
    print(f"Job {job_id}: starting")
    await asyncio.sleep(1)  # Suspend this coroutine
    print(f"Job {job_id}: finished")
    return f"Result from {job_id}"


def worker(worker_id):
    async def run_jobs():
        # Gather this worker's coroutine results.
        return await asyncio.gather(
            async_job(f"{worker_id}-A"),
            async_job(f"{worker_id}-B"),
        )

    # Creates and runs an event loop on this worker thread
    # asyncio.run returns whatever run_jobs returns.
    return asyncio.run(run_jobs())


async def main():
    loop = asyncio.get_running_loop()

    with ThreadPoolExecutor(max_workers=2) as pool:
        # Main loop is coordinating work to worker threads
        # Gather the return values from both worker invocations.
        results = await asyncio.gather(
            loop.run_in_executor(pool, worker, 1),
            loop.run_in_executor(pool, worker, 2),
        )

    print(results)


if __name__ == "__main__":
    # Creates and runs an event loop on main thread
    asyncio.run(main())
