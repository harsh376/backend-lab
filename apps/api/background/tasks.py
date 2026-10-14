"""Background tasks; pass JSON values rather than request-scoped resources."""

import asyncio
import logging
from dataclasses import asdict
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from apps.api.background.celery_app import celery_app
from apps.api.config import Settings
from backend.services.hold_notifications.hold_notifications import HoldNotifications


@celery_app.task(name="api.ping")
def ping(request_id: str) -> None:
    """Smoke-test delivery without changing application data."""
    logging.getLogger("api-worker").info(
        "background_ping_completed",
        extra={"request_id": request_id, "task_id": ping.request.id},
    )


async def _create_hold_notifications() -> dict[str, int]:
    settings = Settings()
    engine = create_async_engine(settings.database_url)
    try:
        service = HoldNotifications(async_sessionmaker(engine, expire_on_commit=False))
        counts = await service.process_notifications(
            datetime.now(UTC),
            reminder_window=timedelta(minutes=settings.hold_reminder_window_minutes),
            batch_size=settings.hold_notification_batch_size,
        )
        return asdict(counts)
    finally:
        await engine.dispose()


@celery_app.task(
    name="api.create_hold_notifications",
    acks_late=True,
    autoretry_for=(OperationalError,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=5,
)
def create_hold_notifications() -> None:
    """Use a fresh engine within this task's event loop, never API sessions."""
    counts = asyncio.run(_create_hold_notifications())
    logging.getLogger("api-worker").info(
        "hold_notifications_created",
        extra=counts,
    )
