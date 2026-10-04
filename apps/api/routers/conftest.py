import logging

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from apps.api.application import create_app
from apps.api.dependencies import ApplicationDependencies
from apps.api.domains.title import Title
from apps.api.metrics import OpenTelemetryMetrics
from apps.api.repositories.title import PostgresTitleRepository
from apps.api.repositories.user_list import PostgresUserListRepository
from apps.api.services.title import TitleService
from apps.api.services.user_list import UserListService


async def make_app(
    database_sessions,
    repository=None,
    readiness_probe=None,
    user_list_repository=None,
) -> FastAPI:
    repository = repository or PostgresTitleRepository(database_sessions)
    user_list_repository = user_list_repository or PostgresUserListRepository(
        database_sessions
    )
    metrics = OpenTelemetryMetrics()
    logger = logging.getLogger(f"test-{id(metrics)}")
    logger.addHandler(logging.NullHandler())
    service = TitleService(repository, metrics, logger)
    user_list_service = UserListService(user_list_repository, logger)
    dependencies = ApplicationDependencies(
        service=service,
        user_list_service=user_list_service,
        logger=logger,
        metrics=metrics,
        database_sessions=database_sessions,
        readiness_probe=readiness_probe,
    )
    return create_app(dependencies)


@pytest.fixture
async def client(sqlalchemy_sessions):
    repository = PostgresTitleRepository(sqlalchemy_sessions)
    await repository.create(Title(id="movie-123", name="Example Movie"))
    async with AsyncClient(
        transport=ASGITransport(
            app=await make_app(sqlalchemy_sessions, repository=repository)
        ),
        base_url="http://test",
    ) as value:
        yield value
