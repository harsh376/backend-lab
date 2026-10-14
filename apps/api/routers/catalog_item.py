from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Body, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Select, func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.responses import JSONResponse

from apps.api.dependencies import (
    AsyncDatabaseSessionDependency,
    ItemReservationServiceDependency,
    RequestContextDependency,
)
from apps.api.schemas import ErrorResponse, error_response
from backend.db import models
from backend.services.item_reservation.item_reservation import ReservationError

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
            models.Reservation.catalog_item_id,
            func.count().label("count"),
        )
        .where(models.Reservation.status == models.ReservationStatus.ACTIVE)
        .group_by(models.Reservation.catalog_item_id)
        .cte("reservation_counts")
    )
    hold_counts = (
        select(models.Hold.catalog_item_id, func.count().label("count"))
        .where(
            models.Hold.status == models.HoldStatus.ALLOCATED,
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


def workflow_error(exc: Exception, request_id: str) -> JSONResponse:
    if isinstance(exc, ReservationError):
        return error_response(
            status_code=exc.status_code,
            code=exc.code,
            message=str(exc),
            request_id=request_id,
        )
    if isinstance(exc, IntegrityError):
        return error_response(
            status_code=409,
            code="RESERVATION_ALREADY_EXISTS",
            message="Patron already has an active reservation or hold",
            request_id=request_id,
        )
    return error_response(
        status_code=503,
        code="SERVICE_UNAVAILABLE",
        message="Reservation operation could not be completed",
        request_id=request_id,
    )


class ReserveRequest(BaseModel):
    patron_id: int = Field(gt=0)


class ReservationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    catalog_item_id: int
    patron_id: int
    status: models.ReservationStatus


class HoldResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    catalog_item_id: int
    patron_id: int
    status: models.HoldStatus
    expires_at: datetime


WORKFLOW_RESPONSES = {
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
    503: {"model": ErrorResponse},
}


@router.post(
    "/{catalog_item_id}/reserve",
    response_model=ReservationResponse | HoldResponse,
    status_code=status.HTTP_201_CREATED,
    responses=WORKFLOW_RESPONSES,
)
async def reserve_catalog_item(
    catalog_item_id: int,
    body: ReserveRequest,
    response: Response,
    service: ItemReservationServiceDependency,
    context: RequestContextDependency,
) -> ReservationResponse | HoldResponse | JSONResponse:
    try:
        row = await service.reserve(catalog_item_id, body.patron_id)
        if isinstance(row, models.Hold):
            response.headers["Location"] = (
                f"/v1/catalog-items/{catalog_item_id}/holds/{row.id}"
            )
            return HoldResponse.model_validate(row)
        response.headers["Location"] = (
            f"/v1/catalog-items/{catalog_item_id}/reservations/{row.id}"
        )
        return ReservationResponse.model_validate(row)
    except (ReservationError, SQLAlchemyError) as exc:
        return workflow_error(exc, context.request_id)


@router.post(
    "/{catalog_item_id}/holds/allocate",
    response_model=list[HoldResponse],
    responses=WORKFLOW_RESPONSES,
)
async def allocate_catalog_item_holds(
    catalog_item_id: int,
    service: ItemReservationServiceDependency,
    context: RequestContextDependency,
) -> list[HoldResponse] | JSONResponse:
    try:
        rows = await service.allocate_holds(catalog_item_id)
        return [HoldResponse.model_validate(row) for row in rows]
    except (ReservationError, SQLAlchemyError) as exc:
        return workflow_error(exc, context.request_id)


@router.post(
    "/{catalog_item_id}/holds/{hold_id}/cancel",
    response_model=HoldResponse,
    responses=WORKFLOW_RESPONSES,
)
async def cancel_hold_for_catalog_item(
    catalog_item_id: int,
    hold_id: int,
    service: ItemReservationServiceDependency,
    context: RequestContextDependency,
) -> HoldResponse | JSONResponse:
    try:
        row = await service.cancel_hold(hold_id, catalog_item_id=catalog_item_id)
        return HoldResponse.model_validate(row)
    except (ReservationError, SQLAlchemyError) as exc:
        return workflow_error(exc, context.request_id)


@router.post(
    "/{catalog_item_id}/holds/{hold_id}/confirm",
    response_model=ReservationResponse,
    responses=WORKFLOW_RESPONSES,
)
async def confirm_hold_for_catalog_item(
    catalog_item_id: int,
    hold_id: int,
    service: ItemReservationServiceDependency,
    context: RequestContextDependency,
) -> ReservationResponse | JSONResponse:
    try:
        row = await service.confirm_hold(hold_id, catalog_item_id=catalog_item_id)
        return ReservationResponse.model_validate(row)
    except (ReservationError, SQLAlchemyError) as exc:
        return workflow_error(exc, context.request_id)


@router.post(
    "/{catalog_item_id}/reservations/{reservation_id}/cancel",
    response_model=ReservationResponse,
    responses=WORKFLOW_RESPONSES,
)
async def cancel_reservation_for_catalog_item(
    catalog_item_id: int,
    reservation_id: int,
    service: ItemReservationServiceDependency,
    context: RequestContextDependency,
) -> ReservationResponse | JSONResponse:
    try:
        row = await service.cancel_reservation(
            reservation_id, catalog_item_id=catalog_item_id
        )
        return ReservationResponse.model_validate(row)
    except (ReservationError, SQLAlchemyError) as exc:
        return workflow_error(exc, context.request_id)


@router.post(
    "/{catalog_item_id}/reservations/{reservation_id}/return",
    response_model=ReservationResponse,
    responses=WORKFLOW_RESPONSES,
)
async def return_reservation_for_catalog_item(
    catalog_item_id: int,
    reservation_id: int,
    service: ItemReservationServiceDependency,
    context: RequestContextDependency,
) -> ReservationResponse | JSONResponse:
    try:
        row = await service.return_reservation(
            reservation_id, catalog_item_id=catalog_item_id
        )
        return ReservationResponse.model_validate(row)
    except (ReservationError, SQLAlchemyError) as exc:
        return workflow_error(exc, context.request_id)
