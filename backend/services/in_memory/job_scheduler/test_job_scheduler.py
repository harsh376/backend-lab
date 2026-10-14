from dataclasses import FrozenInstanceError

import pytest

from backend.services.in_memory.job_scheduler.job_scheduler import (
    Job,
    JobDoesNotExist,
    JobSchedulerService,
    NotAPendingJobException,
    Payload,
)


def process_job(payload):
    if payload == {"error": True}:
        raise Exception("fail")


@pytest.fixture
def service():
    return JobSchedulerService(executor=process_job)


def test_schedule(service):
    assert (
        service.schedule(
            "job1",
            {},
            5,
        )
        == "job1"
    )


def test_cancel(service):
    service.schedule(
        "job1",
        {},
        5,
    )
    assert service.cancel("job1") == "job1"


def test_cancel_raises_exception(service):
    with pytest.raises(JobDoesNotExist):
        service.cancel("job2")


def test_cancel_raises_exception_not_pending(service):
    service.schedule(
        "job1",
        {},
        5,
    )
    service.cancel("job1")
    with pytest.raises(NotAPendingJobException):
        service.cancel("job1")


def test_get_job(service):
    service.schedule(
        "job1",
        {},
        5,
    )
    assert service.get_job("job1") == Job(
        id_="job1", payload={}, scheduled_time=5, status="pending"
    )


def test_get_raises_job_dne(service):
    with pytest.raises(JobDoesNotExist):
        service.get_job("job1")


def test_run_due(service):
    service.schedule(
        "job1",
        {},
        5,
    )
    service.schedule(
        "job2",
        {},
        10,
    )
    service.schedule(
        "job3",
        {"error": True},
        10,
    )
    service.schedule(
        "job4",
        {},
        11,
    )
    assert service.run_due(10) == (["job1", "job2"], ["job3"])


def test_retries_terminal_failure(service):
    service.schedule(
        "job2",
        {},
        10,
    )
    service.schedule(
        "job3",
        {"error": True},
        10,
    )
    assert service.run_due(10) == (["job2"], ["job3"])
    assert service.run_due(15) == ([], ["job3"])
    assert service.run_due(20) == ([], ["job3"])
    assert service.run_due(25) == ([], [])
    assert service.get_job("job3") == Job(
        id_="job3",
        payload={"error": True},
        scheduled_time=20,
        status="failed",
        attempts=3,
        last_error="fail",
    )


def test_executor_cannot_mutate_payload():
    def executor(payload: Payload):
        payload["name"] = "joe"

    service = JobSchedulerService(executor)

    service.schedule(
        "job1",
        {},
        10,
    )
    assert service.run_due(10) == ([], ["job1"])
    job = service.get_job("job1")
    assert job.payload == {}
    assert job.attempts == 1
    assert "does not support item assignment" in job.last_error


def test_mutating_original_payload_does_not_affect_job(service):
    payload = {"name": "joe"}
    service.schedule(
        "job1",
        payload,
        10,
    )
    payload["name"] = "jane"

    assert service.get_job("job1").payload == {"name": "joe"}


def test_get_job_result_is_immutable(service):
    service.schedule(
        "job1",
        {"name": "joe"},
        10,
    )
    job = service.get_job("job1")

    with pytest.raises(FrozenInstanceError):
        job.status = "cancelled"
    with pytest.raises(TypeError):
        job.payload["name"] = "jane"

    assert service.get_job("job1") == Job(
        id_="job1", payload={"name": "joe"}, scheduled_time=10, status="pending"
    )


def test_earlier_snapshots_keep_their_state_after_transitions(service):
    service.schedule(
        "job1",
        {},
        10,
    )
    before = service.get_job("job1")
    service.run_due(10)

    assert before.status == "pending"
    assert service.get_job("job1").status == "successful"
