"""Test-process configuration that mirrors the Compose telemetry mode."""

import os
from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.db.config import DatabaseSettings
from backend.db.models import Base


def pytest_configure() -> None:
    os.environ["OTEL_SEMCONV_STABILITY_OPT_IN"] = "http"


@pytest.fixture
async def sqlalchemy_sessions() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """A sessionmaker backed by a freshly-created schema for each test.

    Defaults to an isolated in-memory SQLite database. Set TEST_DATABASE_URL
    (e.g. to the instance from `docker compose -f compose/test.yaml up -d`) to
    run the same repository tests against real PostgreSQL instead.
    """
    engine = create_async_engine(DatabaseSettings().test_database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)

    yield async_sessionmaker(engine, expire_on_commit=False)

    await engine.dispose()
