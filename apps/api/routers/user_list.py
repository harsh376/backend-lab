"""User list resource endpoints."""

from typing import Annotated, Literal

from fastapi import APIRouter, Body, Query, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from apps.api.dependencies import (
    LoggerDependency,
    RequestContextDependency,
    UserIdDependency,
    UserListServiceDependency,
)
from apps.api.schemas import ErrorResponse, error_response
from backend.domains.user_list import UserList, UserListContent
from backend.repositories import RepositoryUnavailableError
from backend.repositories.user_list import (
    ContentAlreadyInListError,
    ContentNotFoundError,
    ContentNotInListError,
    UserListAlreadyExistsError,
    UserListNotFoundError,
    UserNotFoundError,
)

router = APIRouter(prefix="/user-lists", tags=["user-lists"])


class CreateUserListRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class AddUserListContentRequest(BaseModel):
    content_id: int


@router.post(
    "",
    response_model=UserList,
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
    context: RequestContextDependency,
    user_list_service: UserListServiceDependency,
    logger: LoggerDependency,
) -> UserList | JSONResponse:
    try:
        return await user_list_service.create_user_list(
            user_id, body.name, context.request_id
        )
    except UserNotFoundError:
        return error_response(
            status_code=404,
            code="USER_NOT_FOUND",
            message="The requesting user does not exist",
            request_id=context.request_id,
        )
    except UserListAlreadyExistsError:
        return error_response(
            status_code=409,
            code="USER_LIST_ALREADY_EXISTS",
            message="A list with this name already exists",
            request_id=context.request_id,
        )
    except RepositoryUnavailableError:
        logger.exception(
            "user_list_repository_unavailable",
            extra={"request_id": context.request_id, "user_id": user_id},
        )
        return error_response(
            status_code=503,
            code="SERVICE_UNAVAILABLE",
            message="The list could not be created",
            request_id=context.request_id,
        )


@router.get(
    "",
    response_model=list[UserList],
    responses={503: {"model": ErrorResponse}},
)
async def retrieve_user_lists(
    user_id: UserIdDependency,
    context: RequestContextDependency,
    user_list_service: UserListServiceDependency,
    logger: LoggerDependency,
    response: Response,
    cursor: Annotated[int | None, Query()] = None,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    sort: Annotated[Literal["asc", "desc"], Query()] = "desc",
) -> list[UserList] | JSONResponse:
    try:
        user_lists = await user_list_service.retrieve_user_lists(
            user_id,
            context.request_id,
            cursor=cursor,
            page_size=page_size,
            sort=sort,
        )
    except RepositoryUnavailableError:
        logger.exception(
            "user_list_repository_unavailable",
            extra={"request_id": context.request_id, "user_id": user_id},
        )
        return error_response(
            status_code=503,
            code="SERVICE_UNAVAILABLE",
            message="The lists could not be loaded",
            request_id=context.request_id,
        )

    if len(user_lists) == page_size:
        response.headers["X-Next-Cursor"] = str(user_lists[-1].id)
    return user_lists


@router.post(
    "/{user_list_id}/contents",
    response_model=UserListContent,
    status_code=status.HTTP_201_CREATED,
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def add_user_list_content(
    user_list_id: int,
    body: Annotated[AddUserListContentRequest, Body()],
    user_id: UserIdDependency,
    context: RequestContextDependency,
    user_list_service: UserListServiceDependency,
    logger: LoggerDependency,
) -> UserListContent | JSONResponse:
    try:
        return await user_list_service.add_user_list_content(
            user_id, user_list_id, body.content_id, context.request_id
        )
    except UserListNotFoundError:
        return error_response(
            status_code=404,
            code="USER_LIST_NOT_FOUND",
            message="The requested list does not exist",
            request_id=context.request_id,
        )
    except ContentNotFoundError:
        return error_response(
            status_code=404,
            code="CONTENT_NOT_FOUND",
            message="The requested content does not exist",
            request_id=context.request_id,
        )
    except ContentAlreadyInListError:
        return error_response(
            status_code=409,
            code="CONTENT_ALREADY_IN_LIST",
            message="This content is already in the list",
            request_id=context.request_id,
        )
    except RepositoryUnavailableError:
        logger.exception(
            "user_list_repository_unavailable",
            extra={"request_id": context.request_id, "user_id": user_id},
        )
        return error_response(
            status_code=503,
            code="SERVICE_UNAVAILABLE",
            message="The content could not be added",
            request_id=context.request_id,
        )


@router.delete(
    "/{user_list_id}/contents/{user_list_content_id}",
    response_model=None,
    status_code=status.HTTP_204_NO_CONTENT,
    responses={404: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
async def remove_user_list_content(
    user_list_id: int,
    user_list_content_id: int,
    user_id: UserIdDependency,
    context: RequestContextDependency,
    user_list_service: UserListServiceDependency,
    logger: LoggerDependency,
) -> Response | JSONResponse:
    try:
        await user_list_service.remove_user_list_content(
            user_id, user_list_id, user_list_content_id, context.request_id
        )
    except UserListNotFoundError:
        return error_response(
            status_code=404,
            code="USER_LIST_NOT_FOUND",
            message="The requested list does not exist",
            request_id=context.request_id,
        )
    except ContentNotInListError:
        return error_response(
            status_code=404,
            code="CONTENT_NOT_IN_LIST",
            message="This content is not in the list",
            request_id=context.request_id,
        )
    except RepositoryUnavailableError:
        logger.exception(
            "user_list_repository_unavailable",
            extra={"request_id": context.request_id, "user_id": user_id},
        )
        return error_response(
            status_code=503,
            code="SERVICE_UNAVAILABLE",
            message="The content could not be removed",
            request_id=context.request_id,
        )

    return Response(status_code=status.HTTP_204_NO_CONTENT)
