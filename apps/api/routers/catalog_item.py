from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Body, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import Select, func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.responses import JSONResponse

from apps.api.db import models
from apps.api.dependencies import (
    AsyncDatabaseSessionDependency,
    RequestContextDependency,
)
from apps.api.schemas import ErrorResponse, error_response

router = APIRouter(prefix="/catalog-items", tags=["catalog-items"])


def catalog_items_with_availability(
    now: datetime | None = None,
) -> Select[tuple[models.CatalogItem, int]]:
    """Count remaining copies, excluding cancelled reservations and inactive holds.

    Writers must lock the catalog item before checking and consuming capacity.
    """
    now = now if now is not None else datetime.now(UTC)
    reservation_counts = (
        select(
            models.CatalogItemReservation.catalog_item_id,
            func.count().label("count"),
        )
        .where(models.CatalogItemReservation.status == models.Status.CONFIRMED)
        .group_by(models.CatalogItemReservation.catalog_item_id)
        .cte("reservation_counts")
    )
    hold_counts = (
        select(models.Hold.catalog_item_id, func.count().label("count"))
        .where(
            models.Hold.status == models.HoldStatus.CONFIRMED,
            models.Hold.expires_at > now,
        )
        .group_by(models.Hold.catalog_item_id)
        .cte("hold_counts")
    )

    available_count = (
        models.CatalogItem.quantity
        - func.coalesce(reservation_counts.c.count, 0)
        - func.coalesce(hold_counts.c.count, 0)
    )
    stmt = (
        select(
            models.CatalogItem,
            available_count.label("available_count"),
        )
        .outerjoin(
            reservation_counts,
            reservation_counts.c.catalog_item_id == models.CatalogItem.id,
        )
        .outerjoin(hold_counts, hold_counts.c.catalog_item_id == models.CatalogItem.id)
    )
    return stmt


class CreateCatalogItemRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=200)
    item_type: models.CatalogItemType
    quantity: int


class CreateCatalogItemResponse(BaseModel):
    id: int
    name: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=200)
    item_type: models.CatalogItemType
    quantity: int


class GetCatalogItemResponse(BaseModel):
    id: int
    name: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=200)
    item_type: models.CatalogItemType
    quantity: int
    item_status: Literal["available", "not_available"]


@router.post(
    path="",
    response_model=CreateCatalogItemResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        409: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def create_catalog_item(
    body: Annotated[CreateCatalogItemRequest, Body()],
    session: AsyncDatabaseSessionDependency,
    context: RequestContextDependency,
) -> CreateCatalogItemResponse | JSONResponse:

    try:
        async with session.begin():
            row = models.CatalogItem(
                name=body.name,
                item_type=body.item_type,
                category=body.category,
                quantity=body.quantity,
            )
            session.add(row)
            await session.flush()
    except IntegrityError:
        return error_response(
            status_code=409,
            code="CATALOG_ITEM_ALREADY_EXISTS",
            message="Catalog item already exists",
            request_id=context.request_id,
        )
    except SQLAlchemyError:
        return error_response(
            status_code=503,
            code="SERVICE_UNAVAILABLE",
            message="Catalog item could not be created",
            request_id=context.request_id,
        )
    return CreateCatalogItemResponse(
        id=row.id,
        name=row.name,
        category=row.category,
        item_type=row.item_type,
        quantity=row.quantity,
    )


@router.get(
    path="",
    response_model=list[GetCatalogItemResponse],
    status_code=status.HTTP_200_OK,
    responses={
        503: {"model": ErrorResponse},
    },
)
async def get_catalog_items(
    session: AsyncDatabaseSessionDependency,
    context: RequestContextDependency,
    search_query: Annotated[str | None, Query()] = None,
    item_type: Annotated[models.CatalogItemType | None, Query()] = None,
    item_status: Annotated[
        Literal["available", "not_available"] | None, Query()
    ] = None,
) -> list[GetCatalogItemResponse] | JSONResponse:
    try:
        stmt = catalog_items_with_availability()
        available_count = stmt.selected_columns.available_count
        if search_query is not None:
            stmt = stmt.where(
                models.CatalogItem.name.icontains(search_query, autoescape=True)
            )

        if item_type is not None:
            stmt = stmt.where(models.CatalogItem.item_type == item_type)

        if item_status == "available":
            stmt = stmt.where(available_count > 0)
        elif item_status == "not_available":
            stmt = stmt.where(available_count <= 0)

        stmt = stmt.order_by(models.CatalogItem.id.asc())

        result = await session.execute(stmt)

        return [
            GetCatalogItemResponse(
                id=row.id,
                name=row.name,
                category=row.category,
                item_type=row.item_type,
                quantity=row.quantity,
                item_status="available" if available_count > 0 else "not_available",
            )
            for row, available_count in result
        ]

    except SQLAlchemyError:
        return error_response(
            status_code=503,
            code="SERVICE_UNAVAILABLE",
            message="Catalog items could not be fetched",
            request_id=context.request_id,
        )


class CreateReservationRequest(BaseModel):
    patron_id: int


class CreateReservationResponse(BaseModel):
    id: int
    catalog_item_id: int
    patron_id: int
    status: models.Status


@router.post(
    path="/{catalog_item_id}/reservations",
    response_model=CreateReservationResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def create_catalog_item_reservation(
    catalog_item_id: int,
    body: Annotated[CreateReservationRequest, Body()],
    session: AsyncDatabaseSessionDependency,
    request_context: RequestContextDependency,
) -> CreateReservationResponse | JSONResponse:
    try:
        async with session.begin():
            # Lock before checking capacity to serialize reservation writers.
            result = await session.execute(
                select(models.CatalogItem)
                .where(models.CatalogItem.id == catalog_item_id)
                .with_for_update()
            )
            item = result.scalar_one_or_none()
            if item is None:
                return error_response(
                    status_code=404,
                    code="CATALOG_ITEM_NOT_FOUND",
                    message="Catalog item does not exist",
                    request_id=request_context.request_id,
                )
            if await session.get(models.Patron, body.patron_id) is None:
                return error_response(
                    status_code=404,
                    code="PATRON_NOT_FOUND",
                    message="Patron does not exist",
                    request_id=request_context.request_id,
                )
            result = await session.execute(
                catalog_items_with_availability().where(
                    models.CatalogItem.id == catalog_item_id
                )
            )
            _, available_count = result.one()
            if available_count <= 0:
                return error_response(
                    status_code=409,
                    code="CATALOG_ITEM_NOT_AVAILABLE",
                    message="Catalog item is not available",
                    request_id=request_context.request_id,
                )
            reservation = models.CatalogItemReservation(
                catalog_item_id=catalog_item_id,
                patron_id=body.patron_id,
                status=models.Status.CONFIRMED,
            )
            session.add(reservation)
            await session.flush()
            response = CreateReservationResponse(
                id=reservation.id,
                catalog_item_id=reservation.catalog_item_id,
                patron_id=reservation.patron_id,
                status=reservation.status,
            )
        return response
    except IntegrityError:
        return error_response(
            status_code=409,
            code="RESERVATION_ALREADY_EXISTS",
            message="Patron already has a confirmed reservation for this item",
            request_id=request_context.request_id,
        )
    except SQLAlchemyError:
        return error_response(
            status_code=503,
            code="SERVICE_UNAVAILABLE",
            message="Reservation could not be created",
            request_id=request_context.request_id,
        )
