"""FastAPI dependency providers for application-level services."""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated, cast

from fastapi import Depends, Request

from app.service import TitleService

ReadinessProbe = Callable[[], Awaitable[bool]]


@dataclass(frozen=True, slots=True)
class ApplicationDependencies:
    """Dependencies shared by the application's request handlers."""

    service: TitleService
    logger: logging.Logger
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


def get_logger(dependencies: ApplicationDependenciesDependency) -> logging.Logger:
    return dependencies.logger


def get_readiness_probe(
    dependencies: ApplicationDependenciesDependency,
) -> ReadinessProbe | None:
    return dependencies.readiness_probe


RequestContextDependency = Annotated[RequestContext, Depends(get_request_context)]
TitleServiceDependency = Annotated[TitleService, Depends(get_title_service)]
LoggerDependency = Annotated[logging.Logger, Depends(get_logger)]
ReadinessProbeDependency = Annotated[
    ReadinessProbe | None, Depends(get_readiness_probe)
]
