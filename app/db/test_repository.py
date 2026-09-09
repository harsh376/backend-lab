import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Base
from app.db.repository import (
    PostgresTitleRepository,
    TitleAlreadyExistsError,
    TitleNotFoundError,
)
from app.domain import Title


@pytest.fixture
async def repository():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    repository = PostgresTitleRepository(
        async_sessionmaker(engine, expire_on_commit=False)
    )
    yield repository
    await engine.dispose()


async def test_create_and_get_title(repository: PostgresTitleRepository) -> None:
    title = Title(
        id="movie-123",
        name="Example Movie",
        description="A repository integration test.",
    )

    assert await repository.create(title) == title
    assert await repository.get_by_id(title.id) == title


async def test_duplicate_title_is_a_domain_specific_error(
    repository: PostgresTitleRepository,
) -> None:
    title = Title(id="movie-123", name="Example Movie")
    await repository.create(title)

    with pytest.raises(TitleAlreadyExistsError):
        await repository.create(title)


async def test_missing_title_is_a_domain_specific_error(
    repository: PostgresTitleRepository,
) -> None:
    with pytest.raises(TitleNotFoundError):
        await repository.get_by_id("missing")
