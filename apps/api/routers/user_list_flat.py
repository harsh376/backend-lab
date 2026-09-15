"""Phase-one user list endpoint with direct ORM persistence."""

from typing import Annotated

from fastapi import APIRouter, Body, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from apps.api.db.models import User as UserRow
from apps.api.db.models import UserList as UserListRow
from apps.api.dependencies import (
    AsyncDatabaseSessionDependency,
    LoggerDependency,
    RequestContextDependency,
    UserIdDependency,
)
from apps.api.schemas import ErrorResponse, error_response

router = APIRouter(prefix="/user-lists-flat", tags=["user-lists-flat"])


class CreateUserListRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class UserListResponse(BaseModel):
    id: int
    user_id: int
    name: str = Field(min_length=1, max_length=200)


@router.post(
    "",
    response_model=UserListResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def create_user_list(
    body: Annotated[CreateUserListRequest, Body()],
    user_id: UserIdDependency,
    session: AsyncDatabaseSessionDependency,
    context: RequestContextDependency,
    logger: LoggerDependency,
) -> UserListResponse | JSONResponse:
    try:
        async with session.begin():
            user_exists = await session.scalar(
                select(UserRow.id).where(UserRow.id == user_id)
            )
            if user_exists is None:
                logger.warning(
                    "user_list_flat_user_not_found",
                    extra={"request_id": context.request_id, "user_id": user_id},
                )
                return error_response(
                    status_code=404,
                    code="USER_NOT_FOUND",
                    message="The requesting user does not exist",
                    request_id=context.request_id,
                )

            row = UserListRow(user_id=user_id, name=body.name)
            session.add(row)
            await session.flush()
            await session.refresh(row)
    except IntegrityError:
        logger.warning(
            "user_list_flat_already_exists",
            extra={"request_id": context.request_id, "user_id": user_id},
        )
        return error_response(
            status_code=409,
            code="USER_LIST_ALREADY_EXISTS",
            message="A list with this name already exists",
            request_id=context.request_id,
        )
    except SQLAlchemyError:
        logger.exception(
            "user_list_flat_database_error",
            extra={"request_id": context.request_id, "user_id": user_id},
        )
        return error_response(
            status_code=503,
            code="SERVICE_UNAVAILABLE",
            message="The list could not be created",
            request_id=context.request_id,
        )

    return UserListResponse(id=row.id, user_id=row.user_id, name=row.name)
