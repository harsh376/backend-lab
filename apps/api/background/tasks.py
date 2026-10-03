"""Background tasks; pass JSON values rather than request-scoped resources."""

import logging

from apps.api.background.celery_app import celery_app


@celery_app.task(name="api.ping")
def ping(request_id: str) -> None:
    """Smoke-test delivery without changing application data."""
    logging.getLogger("api-worker").info(
        "background_ping_completed",
        extra={"request_id": request_id, "task_id": ping.request.id},
    )
