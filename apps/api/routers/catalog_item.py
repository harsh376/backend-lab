from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Body, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.responses import JSONResponse

from apps.api.db import models
from apps.api.dependencies import (
    AsyncDatabaseSessionDependency,
    RequestContextDependency,
)
from apps.api.schemas import ErrorResponse, error_response

router = APIRouter(prefix="/catalog-items", tags=["catalog-items"])


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
        now = datetime.now(UTC)
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
            .outerjoin(
                hold_counts, hold_counts.c.catalog_item_id == models.CatalogItem.id
            )
        )
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
