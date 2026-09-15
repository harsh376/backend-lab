"""FastAPI dependency providers for application-level services."""

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated, cast

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from apps.api.metrics import OpenTelemetryMetrics
from apps.api.services.title import TitleService
from apps.api.services.user_list import UserListService

ReadinessProbe = Callable[[], Awaitable[bool]]


@dataclass(frozen=True, slots=True)
class ApplicationDependencies:
    """Dependencies shared by the application's request handlers."""

    service: TitleService
    user_list_service: UserListService
    logger: logging.Logger
    metrics: OpenTelemetryMetrics
    database_sessions: async_sessionmaker[AsyncSession] | None = None
    readiness_probe: ReadinessProbe | None = None


@dataclass(frozen=True, slots=True)
class RequestContext:
    """Context associated with a single HTTP request."""

    request_id: str


def get_application_dependencies(request: Request) -> ApplicationDependencies:
    return cast(ApplicationDependencies, request.app.state.dependencies)


ApplicationDependenciesDependency = Annotated[
    ApplicationDependencies, Depends(get_application_dependencies)
]


def get_request_context(request: Request) -> RequestContext:
    return RequestContext(request_id=request.state.request_id)


def get_title_service(
    dependencies: ApplicationDependenciesDependency,
) -> TitleService:
    return dependencies.service


def get_user_list_service(
    dependencies: ApplicationDependenciesDependency,
) -> UserListService:
    return dependencies.user_list_service


def get_logger(dependencies: ApplicationDependenciesDependency) -> logging.Logger:
    return dependencies.logger


def get_metrics(
    dependencies: ApplicationDependenciesDependency,
) -> OpenTelemetryMetrics:
    return dependencies.metrics


def get_readiness_probe(
    dependencies: ApplicationDependenciesDependency,
) -> ReadinessProbe | None:
    return dependencies.readiness_probe


async def get_async_database_session(
    dependencies: ApplicationDependenciesDependency,
) -> AsyncIterator[AsyncSession]:
    if dependencies.database_sessions is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database sessions are unavailable",
        )

    async with dependencies.database_sessions() as session:
        yield session


def get_user_id(x_user_id: Annotated[int | None, Header()] = None) -> int:
    """Authentication is out of scope; the caller passes their user ID directly."""
    if x_user_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-User-Id header is required",
        )
    return x_user_id


RequestContextDependency = Annotated[RequestContext, Depends(get_request_context)]
TitleServiceDependency = Annotated[TitleService, Depends(get_title_service)]
UserListServiceDependency = Annotated[UserListService, Depends(get_user_list_service)]
LoggerDependency = Annotated[logging.Logger, Depends(get_logger)]
MetricsDependency = Annotated[OpenTelemetryMetrics, Depends(get_metrics)]
ReadinessProbeDependency = Annotated[
    ReadinessProbe | None, Depends(get_readiness_probe)
]
AsyncDatabaseSessionDependency = Annotated[
    AsyncSession, Depends(get_async_database_session)
]
UserIdDependency = Annotated[int, Depends(get_user_id)]
