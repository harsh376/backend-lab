"""Title resource endpoints."""

from typing import Annotated

from fastapi import APIRouter, Body, status
from fastapi.responses import JSONResponse

from apps.api.dependencies import (
    LoggerDependency,
    RequestContextDependency,
    TitleServiceDependency,
)
from apps.api.domains.title import Title
from apps.api.repositories import RepositoryUnavailableError
from apps.api.repositories.title import TitleAlreadyExistsError, TitleNotFoundError
from apps.api.schemas import ErrorResponse, error_response

router = APIRouter(prefix="/titles", tags=["titles"])


@router.get(
    "/{title_id}",
    response_model=Title,
    responses={404: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
async def get_title(
    title_id: str,
    context: RequestContextDependency,
    title_service: TitleServiceDependency,
    logger: LoggerDependency,
) -> Title | JSONResponse:
    try:
        return await title_service.get(title_id, context.request_id)
    except TitleNotFoundError:
        return error_response(
            status_code=404,
            code="TITLE_NOT_FOUND",
            message="The requested title does not exist",
            request_id=context.request_id,
        )
    except RepositoryUnavailableError:
        logger.exception(
            "title_repository_unavailable",
            extra={"request_id": context.request_id, "title_id": title_id},
        )
        return error_response(
            status_code=503,
            code="SERVICE_UNAVAILABLE",
            message="The title could not be loaded",
            request_id=context.request_id,
        )


@router.post(
    "",
    response_model=Title,
    status_code=status.HTTP_201_CREATED,
    responses={409: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
async def create_title(
    title: Annotated[Title, Body()],
    context: RequestContextDependency,
    title_service: TitleServiceDependency,
    logger: LoggerDependency,
) -> Title | JSONResponse:
    try:
        return await title_service.create(title, context.request_id)
    except TitleAlreadyExistsError:
        return error_response(
            status_code=409,
            code="TITLE_ALREADY_EXISTS",
            message="A title with this ID already exists",
            request_id=context.request_id,
        )
    except RepositoryUnavailableError:
        logger.exception(
            "title_repository_unavailable",
            extra={"request_id": context.request_id, "title_id": title.id},
        )
        return error_response(
            status_code=503,
            code="SERVICE_UNAVAILABLE",
            message="The title could not be created",
            request_id=context.request_id,
        )
