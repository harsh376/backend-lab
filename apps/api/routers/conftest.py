import logging

import pytest
from httpx import ASGITransport, AsyncClient

from apps.api.application import create_app
from apps.api.dependencies import ApplicationDependencies
from apps.api.domains.title import Title
from apps.api.metrics import OpenTelemetryMetrics
from apps.api.repositories.title import InMemoryTitleRepository
from apps.api.repositories.user_list import SqliteUserListRepository
from apps.api.services.title import TitleService
from apps.api.services.user_list import UserListService


async def make_app(repository=None, readiness_probe=None, user_list_repository=None):
    repository = repository or InMemoryTitleRepository(
        [Title(id="movie-123", name="Example Movie")]
    )
    if user_list_repository is None:
        user_list_repository = SqliteUserListRepository()
        await user_list_repository.initialize()
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
        readiness_probe=readiness_probe,
    )
    return create_app(dependencies)


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=await make_app()),
        base_url="http://test",
    ) as value:
        yield value
