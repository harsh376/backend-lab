"""Create notifications from committed reservation state, safely on repeated runs."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from apps.api.db import models


@dataclass
class NotificationCounts:
    expiring: int = 0
    converted: int = 0


class HoldNotifications:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]):
        self.sessions = sessions

    async def process_notifications(
        self,
        now: datetime,
        *,
        reminder_window: timedelta = timedelta(hours=2),
        batch_size: int = 200,
    ) -> NotificationCounts:
        """Process at most batch_size candidates per kind; later ticks catch up.

        Lock catalog items, matching ItemReservation's lock order, then reload
        each hold before deciding. Existing reminders remain historical records.
        """
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        if reminder_window <= timedelta(0) or batch_size <= 0:
            raise ValueError("reminder_window and batch_size must be positive")
        now = now.astimezone(UTC)
        counts = NotificationCounts()
        for kind in models.NotificationKind:
            async with self.sessions() as session:
                eligible = (
                    (models.Hold.status == models.HoldStatus.ALLOCATED)
                    & (models.Hold.expires_at > now)
                    & (models.Hold.expires_at <= now + reminder_window)
                    if kind == models.NotificationKind.HOLD_EXPIRING
                    else (models.Hold.status == models.HoldStatus.CONVERTED)
                    & exists().where(models.Reservation.hold_id == models.Hold.id)
                )
                candidates = list(
                    await session.execute(
                        select(models.Hold.id, models.Hold.catalog_item_id)
                        .where(
                            eligible,
                            ~exists().where(
                                models.Notification.hold_id == models.Hold.id,
                                models.Notification.kind == kind,
                            ),
                        )
                        .order_by(models.Hold.expires_at, models.Hold.id)
                        .limit(batch_size)
                    )
                )
            for hold_id, item_id in candidates:
                async with self.sessions.begin() as session:
                    await session.scalar(
                        select(models.CatalogItem)
                        .where(models.CatalogItem.id == item_id)
                        .with_for_update()
                    )
                    hold: models.Hold | None = await session.get(models.Hold, hold_id)
                    if hold is None:
                        continue
                    reservation_id = None
                    if kind == models.NotificationKind.HOLD_EXPIRING:
                        expiry = self._utc(hold.expires_at)
                        if hold.status != models.HoldStatus.ALLOCATED or not (
                            now < expiry <= now + reminder_window
                        ):
                            continue
                        scheduled = expiry - reminder_window
                        message = f"Confirm your hold before {expiry.isoformat()}."
                    else:
                        if hold.status != models.HoldStatus.CONVERTED:
                            continue
                        reservation: models.Reservation | None = await session.scalar(
                            select(models.Reservation).where(
                                models.Reservation.hold_id == hold.id
                            )
                        )
                        if reservation is None:
                            continue
                        reservation_id = reservation.id
                        scheduled = self._utc(reservation.created_at)
                        message = (
                            "Your hold has been converted to reservation "
                            f"{reservation.id}."
                        )
                    # The item lock serializes workers. Recheck after acquiring
                    # it because another worker may have processed our candidate.
                    existing = await session.scalar(
                        select(models.Notification.id).where(
                            models.Notification.hold_id == hold.id,
                            models.Notification.kind == kind,
                        )
                    )
                    if existing is not None:
                        continue
                    session.add(
                        models.Notification(
                            patron_id=hold.patron_id,
                            hold_id=hold.id,
                            reservation_id=reservation_id,
                            kind=kind,
                            message=message,
                            scheduled_at=scheduled,
                        )
                    )
                    await session.flush()
                # Count only committed notifications.
                if kind == models.NotificationKind.HOLD_EXPIRING:
                    counts.expiring += 1
                else:
                    counts.converted += 1
        return counts

    @staticmethod
    def _utc(value: datetime) -> datetime:
        return (
            value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        )
