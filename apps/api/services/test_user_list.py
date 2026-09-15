"""Tests for the user list application service."""

import logging

import pytest

from apps.api.domains.user_list import UserList, UserListContent
from apps.api.repositories import RepositoryUnavailableError
from apps.api.repositories.user_list import (
    ContentAlreadyInListError,
    ContentNotFoundError,
    ContentNotInListError,
    SqliteUserListRepository,
    UserListAlreadyExistsError,
    UserListNotFoundError,
)
from apps.api.services.user_list import UserListService

USER_ID = 1
CONTENT_ID = 1
MISSING_CONTENT_ID = 999
MISSING_LIST_ID = 999


class UnavailableUserListRepository:
    async def create_user_list(self, user_id: int, list_name: str) -> UserList:
        raise RepositoryUnavailableError(list_name)

    async def retrieve_user_lists(
        self,
        user_id: int,
        *,
        cursor: int | None = None,
        page_size: int = 20,
        sort: str = "desc",
    ) -> list[UserList]:
        raise RepositoryUnavailableError(user_id)

    async def get_user_list(self, user_id: int, user_list_id: int) -> UserList:
        raise RepositoryUnavailableError(user_list_id)

    async def add_content(
        self, user_id: int, user_list_id: int, content_id: int
    ) -> UserListContent:
        raise RepositoryUnavailableError(content_id)

    async def remove_content(
        self, user_id: int, user_list_id: int, user_list_content_id: int
    ) -> None:
        raise RepositoryUnavailableError(user_list_content_id)


class RecordingHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[tuple[str, str]] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append((record.operation, record.outcome))


@pytest.fixture
async def repository():
    repository = SqliteUserListRepository()
    await repository.initialize()
    await repository.seed_user(USER_ID)
    await repository.seed_content(CONTENT_ID)
    yield repository
    await repository.close()


def make_service(repository) -> tuple[UserListService, RecordingHandler]:
    handler = RecordingHandler()
    logger = logging.getLogger(f"test-user-list-service-{id(handler)}")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return UserListService(repository, logger), handler


async def test_create_user_list_records_success_and_already_exists(
    repository: SqliteUserListRepository,
) -> None:
    service, handler = make_service(repository)

    created = await service.create_user_list(USER_ID, "Favorites", "request-1")
    assert created.user_id == USER_ID
    assert created.name == "Favorites"

    with pytest.raises(UserListAlreadyExistsError):
        await service.create_user_list(USER_ID, "Favorites", "request-2")

    assert handler.records == [
        ("create_user_list", "success"),
        ("create_user_list", "already_exists"),
    ]


async def test_retrieve_user_lists_records_success(
    repository: SqliteUserListRepository,
) -> None:
    service, handler = make_service(repository)
    existing = await repository.create_user_list(USER_ID, "Favorites")

    result = await service.retrieve_user_lists(USER_ID, "request-1")

    assert result == [existing]
    assert handler.records == [("retrieve_user_lists", "success")]


async def test_get_user_list_records_success_and_not_found(
    repository: SqliteUserListRepository,
) -> None:
    service, handler = make_service(repository)
    existing = await repository.create_user_list(USER_ID, "Favorites")

    result = await service.get_user_list(USER_ID, existing.id, "request-1")
    assert result == existing

    with pytest.raises(UserListNotFoundError):
        await service.get_user_list(USER_ID, MISSING_LIST_ID, "request-2")

    assert handler.records == [
        ("get_user_list", "success"),
        ("get_user_list", "not_found"),
    ]


async def test_add_user_list_content_records_all_outcomes(
    repository: SqliteUserListRepository,
) -> None:
    service, handler = make_service(repository)
    existing = await repository.create_user_list(USER_ID, "Favorites")

    added = await service.add_user_list_content(
        USER_ID, existing.id, CONTENT_ID, "request-1"
    )
    assert added.user_list_id == existing.id
    assert added.content_id == CONTENT_ID

    with pytest.raises(ContentAlreadyInListError):
        await service.add_user_list_content(
            USER_ID, existing.id, CONTENT_ID, "request-2"
        )

    with pytest.raises(ContentNotFoundError):
        await service.add_user_list_content(
            USER_ID, existing.id, MISSING_CONTENT_ID, "request-3"
        )

    with pytest.raises(UserListNotFoundError):
        await service.add_user_list_content(
            USER_ID, MISSING_LIST_ID, CONTENT_ID, "request-4"
        )

    assert handler.records == [
        ("add_user_list_content", "success"),
        ("add_user_list_content", "already_in_list"),
        ("add_user_list_content", "content_not_found"),
        ("add_user_list_content", "list_not_found"),
    ]


async def test_remove_user_list_content_records_all_outcomes(
    repository: SqliteUserListRepository,
) -> None:
    service, handler = make_service(repository)
    existing = await repository.create_user_list(USER_ID, "Favorites")
    added = await service.add_user_list_content(
        USER_ID, existing.id, CONTENT_ID, "request-1"
    )

    result = await service.remove_user_list_content(
        USER_ID, existing.id, added.id, "request-2"
    )
    assert result is None

    with pytest.raises(ContentNotInListError):
        await service.remove_user_list_content(
            USER_ID, existing.id, added.id, "request-3"
        )

    with pytest.raises(UserListNotFoundError):
        await service.remove_user_list_content(
            USER_ID, MISSING_LIST_ID, added.id, "request-4"
        )

    assert handler.records == [
        ("add_user_list_content", "success"),
        ("remove_user_list_content", "success"),
        ("remove_user_list_content", "not_in_list"),
        ("remove_user_list_content", "list_not_found"),
    ]


async def test_repository_unavailability_is_recorded_for_every_operation() -> None:
    service, handler = make_service(UnavailableUserListRepository())

    with pytest.raises(RepositoryUnavailableError):
        await service.create_user_list(USER_ID, "Favorites", "request-1")
    with pytest.raises(RepositoryUnavailableError):
        await service.retrieve_user_lists(USER_ID, "request-2")
    with pytest.raises(RepositoryUnavailableError):
        await service.get_user_list(USER_ID, MISSING_LIST_ID, "request-3")
    with pytest.raises(RepositoryUnavailableError):
        await service.add_user_list_content(
            USER_ID, MISSING_LIST_ID, CONTENT_ID, "request-4"
        )
    with pytest.raises(RepositoryUnavailableError):
        await service.remove_user_list_content(
            USER_ID, MISSING_LIST_ID, CONTENT_ID, "request-5"
        )

    assert handler.records == [
        ("create_user_list", "unavailable"),
        ("retrieve_user_lists", "unavailable"),
        ("get_user_list", "unavailable"),
        ("add_user_list_content", "unavailable"),
        ("remove_user_list_content", "unavailable"),
    ]
