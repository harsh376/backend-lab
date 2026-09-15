import pytest

from apps.api.domains.title import Title
from apps.api.repositories.title import (
    PostgresTitleRepository,
    TitleAlreadyExistsError,
    TitleNotFoundError,
)


@pytest.fixture
async def repository(sqlalchemy_sessions):
    return PostgresTitleRepository(sqlalchemy_sessions)


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
