from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Literal

type JobID = str
type Time = int
type JobStatus = Literal["pending", "successful", "failed", "cancelled"]
type Payload = Mapping
type Executor = Callable[[Payload], None]


@dataclass(frozen=True)
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
            payload=MappingProxyType(dict(payload)),
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

        self.jobs[job_id] = replace(job, status="cancelled")
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
            attempts = job.attempts + 1
            try:
                self.executor(job.payload)
            except Exception as e:
                failed.append(job.id_)
                if attempts < self.max_attempts:
                    job = replace(
                        job,
                        attempts=attempts,
                        last_error=str(e),
                        scheduled_time=now + self.retry_delay,
                    )
                else:
                    job = replace(
                        job, attempts=attempts, last_error=str(e), status="failed"
                    )
            else:
                success.append(job.id_)
                job = replace(
                    job, attempts=attempts, last_error=None, status="successful"
                )
            self.jobs[job.id_] = job

        return success, failed

    def get_job(self, job_id: JobID) -> Job:
        job = self.jobs.get(job_id)
        if job is None:
            raise JobDoesNotExist
        return job
