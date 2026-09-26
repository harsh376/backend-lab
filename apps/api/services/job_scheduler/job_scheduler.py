from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from typing import Literal

type JobID = str
type Time = int
type JobStatus = Literal["pending", "successful", "failed", "cancelled"]
type Payload = dict
type Executor = Callable[[Payload], None]


@dataclass
class Job:
    id_: JobID
    payload: Payload
    scheduled_time: Time
    status: str
    attempts: int = 0
    last_error: str | None = None


class JobDoesNotExist(Exception):
    pass


class DuplicateJob(Exception):
    pass


class NotAPendingJobException(Exception):
    pass


class JobSchedulerService:
    def __init__(self, executor: Executor, max_attempts: int = 3, retry_delay: int = 5):
        self.executor = executor
        self.jobs: dict[JobID, Job] = {}
        self.max_attempts = max_attempts
        self.retry_delay = retry_delay

    def schedule(self, job_id: JobID, payload: Payload, run_at: Time) -> JobID:
        if job_id in self.jobs:
            raise DuplicateJob

        new_job = Job(
            id_=job_id,
            payload=deepcopy(payload),
            scheduled_time=run_at,
            status="pending",
        )
        self.jobs[job_id] = new_job
        return job_id

    def cancel(self, job_id: JobID) -> JobID:
        # Cancelling a pending job prevents its execution.
        job = self.jobs.get(job_id)
        if job is None:
            raise JobDoesNotExist

        if job.status != "pending":
            raise NotAPendingJobException

        job.status = "cancelled"
        return job_id

    def run_due(
        self,
        now: Time,
    ) -> tuple[list[JobID], list[JobID]]:
        pending_jobs: list[Job] = []
        for _, job in self.jobs.items():
            if job.status == "pending" and job.scheduled_time <= now:
                pending_jobs.append(job)
        pending_jobs.sort(key=lambda j: (j.scheduled_time, j.id_))

        success, failed = [], []
        for job in pending_jobs:
            try:
                job.attempts += 1
                self.executor(deepcopy(job.payload))
                job.status = "successful"
                job.last_error = None
                success.append(job.id_)
            except Exception as e:
                failed.append(job.id_)
                job.last_error = str(e)
                if job.attempts < self.max_attempts:
                    job.scheduled_time = now + self.retry_delay
                else:
                    job.status = "failed"

        return success, failed

    def get_job(self, job_id: JobID) -> Job:
        job = self.jobs.get(job_id)
        if job is None:
            raise JobDoesNotExist
        return deepcopy(job)
