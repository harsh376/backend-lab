from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.db import models


class ReservationError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 409):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class ItemReservation:
    """Coordinate holds and reservations with atomic state transitions.

    CatalogItem.quantity represents total stock. Available capacity is total
    stock minus ACTIVE reservations and ALLOCATED holds. Serialize capacity
    changes for each catalog item to prevent concurrent overbooking.
    """

    def __init__(self, sessions: async_sessionmaker[AsyncSession]):
        self.sessions = sessions

    async def reserve(
        self, catalog_item_id: int, patron_id: int, *, allow_waitlist: bool = True
    ) -> models.Hold | models.Reservation:
        """Create an ACTIVE reservation or join the waitlist.

        Allocate eligible existing waiting holds first so new requests cannot
        bypass the queue. If capacity remains, create an ACTIVE reservation;
        otherwise create a WAITING hold. Check capacity and create the record
        atomically. Return the created reservation or hold.
        """
        async with self.sessions.begin() as session:
            item = await self._lock_item(session, catalog_item_id)
            await self._patron(session, patron_id)
            await self._reject_duplicate(session, catalog_item_id, patron_id)
            now = datetime.now(UTC)
            await self._expire(session, catalog_item_id, now)
            await self._allocate(session, item, now)
            if await self._available(session, item) > 0:
                row = models.Reservation(
                    catalog_item_id=catalog_item_id,
                    patron_id=patron_id,
                    status=models.ReservationStatus.ACTIVE,
                )
            elif allow_waitlist:
                row = self._new_hold(catalog_item_id, patron_id, now)
            else:
                raise ReservationError(
                    "CATALOG_ITEM_NOT_AVAILABLE", "Catalog item is not available"
                )
            session.add(row)
            await session.flush()
        return row

    async def cancel_hold(
        self, hold_id: int, *, catalog_item_id: int | None = None
    ) -> models.Hold:
        """Transition a WAITING or ALLOCATED hold to CANCELLED and return it.

        Cancelling an ALLOCATED hold releases capacity and allocates it to
        eligible waiting holds in the same transaction. Return an already
        CANCELLED hold unchanged; reject other states.
        """
        async with self.sessions.begin() as session:
            row, item = await self._record(
                session, models.Hold, hold_id, catalog_item_id
            )
            if row.status == models.HoldStatus.CANCELLED:
                return row
            if row.status not in (
                models.HoldStatus.WAITING,
                models.HoldStatus.ALLOCATED,
            ):
                raise ReservationError(
                    "HOLD_STATUS_TRANSITION_NOT_ALLOWED", "Hold cannot be cancelled"
                )
            row.status = models.HoldStatus.CANCELLED
            await session.flush()
            now = datetime.now(UTC)
            await self._expire(session, item.id, now)
            await self._allocate(session, item, now)
        return row

    async def allocate_holds(self, catalog_item_id: int) -> list[models.Hold]:
        """Allocate eligible WAITING holds up to available capacity.

        Select unexpired holds in FIFO order, using creation time and ID as
        a tie-breaker. Derive the allocation count from available capacity
        and transition selected holds to ALLOCATED atomically. Return newly
        allocated holds in queue order. Requires a persisted queue ordering
        field on Hold.
        """
        async with self.sessions.begin() as session:
            item = await self._lock_item(session, catalog_item_id)
            now = datetime.now(UTC)
            await self._expire(session, item.id, now)
            rows = await self._allocate(session, item, now)
        return rows

    async def confirm_hold(
        self, hold_id: int, *, catalog_item_id: int | None = None
    ) -> models.Reservation:
        """Convert an allocated hold into an ACTIVE reservation.

        Atomically transition an unexpired ALLOCATED hold to CONVERTED and
        create an ACTIVE reservation for its item and patron. This transfers
        allocated capacity without consuming additional capacity. Return the
        reservation; for a CONVERTED hold, return its existing reservation.
        Reject other states and expired allocations. Requires a unique link
        from Reservation to its originating Hold.
        """
        async with self.sessions.begin() as session:
            hold, _ = await self._record(session, models.Hold, hold_id, catalog_item_id)
            if hold.status == models.HoldStatus.CONVERTED:
                row = await session.scalar(
                    select(models.Reservation).where(
                        models.Reservation.hold_id == hold.id
                    )
                )
                if row is None:
                    raise ReservationError(
                        "RESERVATION_NOT_FOUND",
                        "Converted hold has no reservation",
                        404,
                    )
            else:
                expiry = hold.expires_at
                if expiry.tzinfo is None:
                    expiry = expiry.replace(tzinfo=UTC)
                if hold.status != models.HoldStatus.ALLOCATED or expiry <= datetime.now(
                    UTC
                ):
                    raise ReservationError(
                        "HOLD_STATUS_TRANSITION_NOT_ALLOWED",
                        "Hold must be allocated and unexpired",
                    )
                row = models.Reservation(
                    catalog_item_id=hold.catalog_item_id,
                    patron_id=hold.patron_id,
                    hold_id=hold.id,
                    status=models.ReservationStatus.ACTIVE,
                )
                hold.status = models.HoldStatus.CONVERTED
                session.add(row)
                await session.flush()
        return row

    async def cancel_reservation(
        self, reservation_id: int, *, catalog_item_id: int | None = None
    ) -> models.Reservation:
        """Transition an ACTIVE reservation to CANCELLED and return it.

        Release capacity and allocate eligible waiting holds in the same
        transaction. Leave its originating hold CONVERTED. Return an already
        CANCELLED reservation unchanged; reject other states.
        """
        return await self._finish_reservation(
            reservation_id, models.ReservationStatus.CANCELLED, catalog_item_id
        )

    async def return_reservation(
        self, reservation_id: int, *, catalog_item_id: int | None = None
    ) -> models.Reservation:
        """Transition an ACTIVE reservation to RETURNED and return it.

        Release capacity and allocate eligible waiting holds in the same
        transaction. Leave its originating hold CONVERTED. Return an already
        RETURNED reservation unchanged; reject other states.
        """
        return await self._finish_reservation(
            reservation_id, models.ReservationStatus.RETURNED, catalog_item_id
        )

    async def expire_holds(self, catalog_item_id: int) -> list[models.Hold]:
        """Expire due ALLOCATED holds and reallocate their capacity.

        Transition ALLOCATED holds whose expires_at is at or before the current
        time to EXPIRED. Release capacity and allocate eligible waiting holds
        in the same transaction. Return newly expired holds; subsequent calls
        leave already EXPIRED holds unchanged.
        """
        async with self.sessions.begin() as session:
            item = await self._lock_item(session, catalog_item_id)
            now = datetime.now(UTC)
            rows = await self._expire(session, item.id, now)
            await self._allocate(session, item, now)
        return rows

    async def create_hold(self, catalog_item_id: int, patron_id: int) -> models.Hold:
        """Join the queue and allocate immediately if capacity remains."""
        async with self.sessions.begin() as session:
            item = await self._lock_item(session, catalog_item_id)
            await self._patron(session, patron_id)
            await self._reject_duplicate(session, catalog_item_id, patron_id)
            now = datetime.now(UTC)
            await self._expire(session, item.id, now)
            row = self._new_hold(catalog_item_id, patron_id, now)
            session.add(row)
            await session.flush()
            await self._allocate(session, item, now)
        return row

    async def validate_hold(
        self, catalog_item_id: int, hold_id: int, patron_id: int
    ) -> models.Hold:
        """Validate the resource scope of the legacy nested hold endpoint."""
        async with self.sessions.begin() as session:
            row = await session.get(models.Hold, hold_id)
            if (
                row is None
                or row.catalog_item_id != catalog_item_id
                or row.patron_id != patron_id
            ):
                raise ReservationError(
                    "HOLD_DOES_NOT_EXIST", "Hold does not exist", 404
                )
            return row

    async def _lock_item(self, session, item_id):
        item = await session.scalar(
            select(models.CatalogItem)
            .where(models.CatalogItem.id == item_id)
            .with_for_update()
        )
        if item is None:
            raise ReservationError(
                "CATALOG_ITEM_NOT_FOUND", "Catalog item does not exist", 404
            )
        return item

    async def _patron(self, session, patron_id):
        if await session.get(models.Patron, patron_id) is None:
            raise ReservationError("PATRON_NOT_FOUND", "Patron does not exist", 404)

    async def _record(self, session, model, record_id, catalog_item_id=None):
        item_id = await session.scalar(
            select(model.catalog_item_id).where(model.id == record_id)
        )
        if item_id is None or (
            catalog_item_id is not None and item_id != catalog_item_id
        ):
            raise ReservationError("RESOURCE_NOT_FOUND", "Record does not exist", 404)
        item = await self._lock_item(session, item_id)
        row = await session.scalar(
            select(model)
            .where(model.id == record_id)
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise ReservationError("RESOURCE_NOT_FOUND", "Record does not exist", 404)
        return row, item

    async def _reject_duplicate(self, session, item_id, patron_id):
        reservation = await session.scalar(
            select(models.Reservation.id).where(
                models.Reservation.catalog_item_id == item_id,
                models.Reservation.patron_id == patron_id,
                models.Reservation.status == models.ReservationStatus.ACTIVE,
            )
        )
        hold = await session.scalar(
            select(models.Hold.id).where(
                models.Hold.catalog_item_id == item_id,
                models.Hold.patron_id == patron_id,
                models.Hold.status.in_(
                    [models.HoldStatus.WAITING, models.HoldStatus.ALLOCATED]
                ),
                models.Hold.expires_at > datetime.now(UTC),
            )
        )
        if reservation is not None or hold is not None:
            raise ReservationError(
                "RESERVATION_ALREADY_EXISTS",
                "Patron already has an active reservation or hold",
            )

    def _new_hold(self, item_id, patron_id, now):
        return models.Hold(
            catalog_item_id=item_id,
            patron_id=patron_id,
            status=models.HoldStatus.WAITING,
            expires_at=now + timedelta(hours=24),
        )

    async def _available(self, session, item):
        reserved = await session.scalar(
            select(func.count())
            .select_from(models.Reservation)
            .where(
                models.Reservation.catalog_item_id == item.id,
                models.Reservation.status == models.ReservationStatus.ACTIVE,
            )
        )
        allocated = await session.scalar(
            select(func.count())
            .select_from(models.Hold)
            .where(
                models.Hold.catalog_item_id == item.id,
                models.Hold.status == models.HoldStatus.ALLOCATED,
            )
        )
        return max(0, item.quantity - reserved - allocated)

    async def _expire(self, session, item_id, now):
        rows = list(
            await session.scalars(
                select(models.Hold).where(
                    models.Hold.catalog_item_id == item_id,
                    models.Hold.status == models.HoldStatus.ALLOCATED,
                    models.Hold.expires_at <= now,
                )
            )
        )
        for row in rows:
            row.status = models.HoldStatus.EXPIRED
        await session.flush()
        return rows

    async def _allocate(self, session, item, now):
        count = await self._available(session, item)
        rows = list(
            await session.scalars(
                select(models.Hold)
                .where(
                    models.Hold.catalog_item_id == item.id,
                    models.Hold.status == models.HoldStatus.WAITING,
                    models.Hold.expires_at > now,
                )
                .order_by(models.Hold.created_at, models.Hold.id)
                .limit(count)
            )
        )
        for row in rows:
            row.status = models.HoldStatus.ALLOCATED
            row.expires_at = now + timedelta(hours=24)
        await session.flush()
        return rows

    async def _finish_reservation(self, reservation_id, status, catalog_item_id=None):
        async with self.sessions.begin() as session:
            row, item = await self._record(
                session, models.Reservation, reservation_id, catalog_item_id
            )
            if row.status == status:
                return row
            if row.status != models.ReservationStatus.ACTIVE:
                raise ReservationError(
                    "RESERVATION_STATUS_TRANSITION_NOT_ALLOWED",
                    "Reservation is not active",
                )
            row.status = status
            await session.flush()
            now = datetime.now(UTC)
            await self._expire(session, item.id, now)
            await self._allocate(session, item, now)
        return row
