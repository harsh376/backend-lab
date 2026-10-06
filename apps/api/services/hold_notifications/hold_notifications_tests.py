from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from apps.api.db import models
from apps.api.services.hold_notifications.hold_notifications import HoldNotifications
from apps.api.services.item_reservation.item_reservation import ItemReservation

NOW = datetime(2026, 10, 5, 12, tzinfo=UTC)


async def seed(sessions, status=models.HoldStatus.ALLOCATED, expiry=None):
    async with sessions.begin() as session:
        item = models.CatalogItem(
            name="Book",
            category="Fiction",
            item_type=models.CatalogItemType.BOOK,
            quantity=1,
        )
        patron = models.Patron(name="Patron")
        session.add_all([item, patron])
        await session.flush()
        hold = models.Hold(
            catalog_item_id=item.id,
            patron_id=patron.id,
            status=status,
            expires_at=expiry or NOW + timedelta(hours=1),
        )
        session.add(hold)
        await session.flush()
    return hold


@pytest.mark.parametrize(
    "minutes,expected", [(121, 0), (120, 1), (1, 1), (0, 0), (-1, 0)]
)
async def test_expiry_boundaries_and_deduplication(
    sqlalchemy_sessions, minutes, expected
):
    hold = await seed(sqlalchemy_sessions, expiry=NOW + timedelta(minutes=minutes))
    service = HoldNotifications(sqlalchemy_sessions)
    assert (await service.process_notifications(NOW)).expiring == expected
    assert (await service.process_notifications(NOW)).expiring == 0
    async with sqlalchemy_sessions() as session:
        rows = list(await session.scalars(select(models.Notification)))
    assert len(rows) == expected
    if rows:
        assert rows[0].hold_id == hold.id
        assert rows[0].reservation_id is None
        assert rows[0].scheduled_at.replace(tzinfo=UTC) == (
            hold.expires_at - timedelta(hours=2)
        )


@pytest.mark.parametrize(
    "status",
    [models.HoldStatus.WAITING, models.HoldStatus.CANCELLED, models.HoldStatus.EXPIRED],
)
async def test_ineligible_states(sqlalchemy_sessions, status):
    await seed(sqlalchemy_sessions, status=status)
    assert (
        await HoldNotifications(sqlalchemy_sessions).process_notifications(NOW)
    ).expiring == 0


async def test_conversion_catchup_even_after_reservation_cancelled(sqlalchemy_sessions):
    hold = await seed(
        sqlalchemy_sessions, expiry=datetime.now(UTC) + timedelta(hours=1)
    )
    reservations = ItemReservation(sqlalchemy_sessions)
    reservation = await reservations.confirm_hold(hold.id)
    await reservations.cancel_reservation(reservation.id)
    service = HoldNotifications(sqlalchemy_sessions)
    counts = await service.process_notifications(datetime.now(UTC) + timedelta(days=3))
    assert (counts.expiring, counts.converted) == (0, 1)
    assert (
        await service.process_notifications(datetime.now(UTC) + timedelta(days=3))
    ).converted == 0
    async with sqlalchemy_sessions() as session:
        row = await session.scalar(select(models.Notification))
        assert row.reservation_id == reservation.id


async def test_reminder_preserved_after_conversion(sqlalchemy_sessions):
    hold = await seed(
        sqlalchemy_sessions, expiry=datetime.now(UTC) + timedelta(hours=1)
    )
    service = HoldNotifications(sqlalchemy_sessions)
    assert (await service.process_notifications(datetime.now(UTC))).expiring == 1
    await ItemReservation(sqlalchemy_sessions).confirm_hold(hold.id)
    counts = await service.process_notifications(datetime.now(UTC))
    assert (counts.expiring, counts.converted) == (0, 1)
    async with sqlalchemy_sessions() as session:
        assert len(list(await session.scalars(select(models.Notification)))) == 2


async def test_batch_catches_up_without_starvation(sqlalchemy_sessions):
    await seed(sqlalchemy_sessions)
    async with sqlalchemy_sessions.begin() as session:
        patron = models.Patron(name="Second")
        session.add(patron)
        await session.flush()
        session.add(
            models.Hold(
                catalog_item_id=1,
                patron_id=patron.id,
                status=models.HoldStatus.ALLOCATED,
                expires_at=NOW + timedelta(minutes=10),
            )
        )
    service = HoldNotifications(sqlalchemy_sessions)
    assert (await service.process_notifications(NOW, batch_size=1)).expiring == 1
    assert (await service.process_notifications(NOW, batch_size=1)).expiring == 1
    assert (await service.process_notifications(NOW, batch_size=1)).expiring == 0


async def test_state_rechecked_after_candidate_scan(sqlalchemy_sessions, monkeypatch):
    from sqlalchemy.ext.asyncio import AsyncSession

    await seed(sqlalchemy_sessions)
    original_get = AsyncSession.get

    async def cancel_before_reload(session, entity, ident, **kwargs):
        if entity is models.Hold:
            from sqlalchemy import update

            await session.execute(
                update(models.Hold)
                .where(models.Hold.id == ident)
                .values(status=models.HoldStatus.CANCELLED)
            )
        return await original_get(session, entity, ident, **kwargs)

    monkeypatch.setattr(AsyncSession, "get", cancel_before_reload)
    assert (
        await HoldNotifications(sqlalchemy_sessions).process_notifications(NOW)
    ).expiring == 0


async def test_failed_insert_rolls_back_and_can_retry(sqlalchemy_sessions, monkeypatch):
    from sqlalchemy.ext.asyncio import AsyncSession

    await seed(sqlalchemy_sessions)
    original_flush = AsyncSession.flush

    async def fail_after_flush(session, *args, **kwargs):
        await original_flush(session, *args, **kwargs)
        raise RuntimeError("worker interrupted before commit")

    with monkeypatch.context() as patch:
        patch.setattr(AsyncSession, "flush", fail_after_flush)
        with pytest.raises(RuntimeError):
            await HoldNotifications(sqlalchemy_sessions).process_notifications(NOW)
    assert (
        await HoldNotifications(sqlalchemy_sessions).process_notifications(NOW)
    ).expiring == 1


async def test_concurrent_postgres_workers(sqlalchemy_sessions):
    import asyncio

    if sqlalchemy_sessions.kw["bind"].dialect.name != "postgresql":
        pytest.skip("SQLite does not implement PostgreSQL row locks")
    await seed(sqlalchemy_sessions)
    service = HoldNotifications(sqlalchemy_sessions)
    results = await asyncio.gather(
        service.process_notifications(NOW), service.process_notifications(NOW)
    )
    assert sum(result.expiring for result in results) == 1
