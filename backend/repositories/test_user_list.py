import pytest

from backend.db.models import Content as ContentRow
from backend.db.models import User as UserRow
from backend.repositories.user_list import (
    ContentAlreadyInListError,
    ContentNotFoundError,
    ContentNotInListError,
    PostgresUserListRepository,
    UserListAlreadyExistsError,
    UserListNotFoundError,
    UserNotFoundError,
)

USER_ID = 1
OTHER_USER_ID = 2
MISSING_USER_ID = 999
CONTENT_ID = 1
OTHER_CONTENT_ID = 2
MISSING_CONTENT_ID = 999
MISSING_LIST_ID = 999


@pytest.fixture
async def repository(sqlalchemy_sessions):
    async with sqlalchemy_sessions() as session, session.begin():
        session.add_all(
            [
                UserRow(id=USER_ID, name="Alice"),
                UserRow(id=OTHER_USER_ID, name="Bob"),
                ContentRow(id=CONTENT_ID, title="Movie A", description="desc"),
                ContentRow(id=OTHER_CONTENT_ID, title="Movie B", description="desc"),
            ]
        )

    return PostgresUserListRepository(sqlalchemy_sessions)


async def test_create_and_get_user_list(
    repository: PostgresUserListRepository,
) -> None:
    created = await repository.create_user_list(USER_ID, "Favorites")

    assert created.user_id == USER_ID
    assert created.name == "Favorites"
    assert await repository.get_user_list(USER_ID, created.id) == created


async def test_create_user_list_for_missing_user_is_a_domain_specific_error(
    repository: PostgresUserListRepository,
) -> None:
    with pytest.raises(UserNotFoundError):
        await repository.create_user_list(MISSING_USER_ID, "Favorites")


async def test_duplicate_list_name_for_same_user_is_a_domain_specific_error(
    repository: PostgresUserListRepository,
) -> None:
    await repository.create_user_list(USER_ID, "Favorites")

    with pytest.raises(UserListAlreadyExistsError):
        await repository.create_user_list(USER_ID, "Favorites")


async def test_duplicate_list_name_is_allowed_across_different_users(
    repository: PostgresUserListRepository,
) -> None:
    await repository.create_user_list(USER_ID, "Favorites")

    other_users_list = await repository.create_user_list(OTHER_USER_ID, "Favorites")

    assert other_users_list.user_id == OTHER_USER_ID


async def test_missing_user_list_is_a_domain_specific_error(
    repository: PostgresUserListRepository,
) -> None:
    with pytest.raises(UserListNotFoundError):
        await repository.get_user_list(USER_ID, MISSING_LIST_ID)


async def test_user_list_owned_by_another_user_is_not_found(
    repository: PostgresUserListRepository,
) -> None:
    created = await repository.create_user_list(USER_ID, "Favorites")

    with pytest.raises(UserListNotFoundError):
        await repository.get_user_list(OTHER_USER_ID, created.id)


async def test_retrieve_user_lists_returns_only_the_users_lists(
    repository: PostgresUserListRepository,
) -> None:
    await repository.create_user_list(USER_ID, "Favorites")
    await repository.create_user_list(OTHER_USER_ID, "Watch Later")

    lists = await repository.retrieve_user_lists(USER_ID)

    assert [user_list.name for user_list in lists] == ["Favorites"]


async def test_retrieve_user_lists_returns_most_recently_created_first(
    repository: PostgresUserListRepository,
) -> None:
    first = await repository.create_user_list(USER_ID, "Favorites")
    second = await repository.create_user_list(USER_ID, "Watch Later")

    lists = await repository.retrieve_user_lists(USER_ID)

    assert [user_list.id for user_list in lists] == [second.id, first.id]


async def test_add_content_returns_the_created_user_list_content(
    repository: PostgresUserListRepository,
) -> None:
    created = await repository.create_user_list(USER_ID, "Favorites")

    added = await repository.add_content(USER_ID, created.id, CONTENT_ID)

    assert added.user_list_id == created.id
    assert added.content_id == CONTENT_ID


async def test_add_content_to_missing_user_list_is_a_domain_specific_error(
    repository: PostgresUserListRepository,
) -> None:
    with pytest.raises(UserListNotFoundError):
        await repository.add_content(USER_ID, MISSING_LIST_ID, CONTENT_ID)


async def test_add_missing_content_is_a_domain_specific_error(
    repository: PostgresUserListRepository,
) -> None:
    created = await repository.create_user_list(USER_ID, "Favorites")

    with pytest.raises(ContentNotFoundError):
        await repository.add_content(USER_ID, created.id, MISSING_CONTENT_ID)


async def test_add_duplicate_content_is_a_domain_specific_error(
    repository: PostgresUserListRepository,
) -> None:
    created = await repository.create_user_list(USER_ID, "Favorites")
    await repository.add_content(USER_ID, created.id, CONTENT_ID)

    with pytest.raises(ContentAlreadyInListError):
        await repository.add_content(USER_ID, created.id, CONTENT_ID)


async def test_remove_content_deletes_it(
    repository: PostgresUserListRepository,
) -> None:
    created = await repository.create_user_list(USER_ID, "Favorites")
    added = await repository.add_content(USER_ID, created.id, CONTENT_ID)

    await repository.remove_content(USER_ID, created.id, added.id)

    with pytest.raises(ContentNotInListError):
        await repository.remove_content(USER_ID, created.id, added.id)


async def test_remove_content_not_in_list_is_a_domain_specific_error(
    repository: PostgresUserListRepository,
) -> None:
    created = await repository.create_user_list(USER_ID, "Favorites")

    with pytest.raises(ContentNotInListError):
        await repository.remove_content(USER_ID, created.id, MISSING_CONTENT_ID)


async def test_remove_content_from_missing_user_list_is_a_domain_specific_error(
    repository: PostgresUserListRepository,
) -> None:
    with pytest.raises(UserListNotFoundError):
        await repository.remove_content(USER_ID, MISSING_LIST_ID, MISSING_CONTENT_ID)


async def test_removing_content_does_not_affect_other_content_in_the_list(
    repository: PostgresUserListRepository,
) -> None:
    created = await repository.create_user_list(USER_ID, "Favorites")
    first = await repository.add_content(USER_ID, created.id, CONTENT_ID)
    second = await repository.add_content(USER_ID, created.id, OTHER_CONTENT_ID)

    await repository.remove_content(USER_ID, created.id, first.id)

    with pytest.raises(ContentNotInListError):
        await repository.remove_content(USER_ID, created.id, first.id)

    await repository.remove_content(USER_ID, created.id, second.id)
