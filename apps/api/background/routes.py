"""Endpoints for enqueueing background tasks."""

from fastapi import APIRouter, HTTPException
from kombu.exceptions import OperationalError
from pydantic import BaseModel

from apps.api.dependencies import (
    ApplicationDependenciesDependency,
    RequestContextDependency,
)

router = APIRouter(tags=["background"])


class TaskAccepted(BaseModel):
    task_id: str
    status: str = "queued"


@router.post("/ping", status_code=202, response_model=TaskAccepted)
def enqueue_ping(
    dependencies: ApplicationDependenciesDependency,
    context: RequestContextDependency,
) -> TaskAccepted:
    # A synchronous route runs in FastAPI's thread pool: broker I/O must not
    # block the async HTTP event loop.
    if dependencies.task_queue is None:
        raise HTTPException(status_code=503, detail="Task queue is unavailable")
    try:
        result = dependencies.task_queue.send_task(
            "api.ping", kwargs={"request_id": context.request_id}
        )
    except OperationalError as exc:
        dependencies.logger.exception("task_publish_failed")
        raise HTTPException(
            status_code=503, detail="Task queue is unavailable"
        ) from exc
    return TaskAccepted(task_id=result.id)


@router.post("/hold-notifications", status_code=202, response_model=TaskAccepted)
def enqueue_hold_notifications(
    dependencies: ApplicationDependenciesDependency,
) -> TaskAccepted:
    """Request a notification sweep without waiting for worker execution."""
    if dependencies.task_queue is None:
        raise HTTPException(status_code=503, detail="Task queue is unavailable")
    try:
        result = dependencies.task_queue.send_task("api.create_hold_notifications")
    except OperationalError as exc:
        dependencies.logger.exception("task_publish_failed")
        raise HTTPException(
            status_code=503, detail="Task queue is unavailable"
        ) from exc
    return TaskAccepted(task_id=result.id)
