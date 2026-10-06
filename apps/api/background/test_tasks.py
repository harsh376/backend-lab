from unittest.mock import AsyncMock

from apps.api.background import tasks
from apps.api.background.celery_app import celery_app


def test_notification_task_bridge(monkeypatch):
    process = AsyncMock(return_value={"expiring": 1, "converted": 2})
    monkeypatch.setattr(tasks, "_create_hold_notifications", process)
    tasks.create_hold_notifications.run()
    process.assert_awaited_once()


def test_notification_schedule_and_retry_policy():
    entry = celery_app.conf.beat_schedule["create-hold-notifications"]
    assert entry["task"] == tasks.create_hold_notifications.name
    assert entry["schedule"] > 0
    assert tasks.create_hold_notifications.acks_late
    assert tasks.create_hold_notifications.max_retries == 5


def test_default_notification_interval():
    from apps.api.config import Settings

    assert (
        Settings(
            _env_file=None, hold_notification_interval_seconds=600
        ).hold_notification_interval_seconds
        == 600
    )
    assert Settings.model_fields["hold_notification_interval_seconds"].default == 600
