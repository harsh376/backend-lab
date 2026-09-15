from httpx import ASGITransport, AsyncClient

from apps.api.db.models import Content as ContentRow
from apps.api.db.models import User as UserRow
from apps.api.domains.user_list import UserList, UserListContent
from apps.api.repositories import RepositoryUnavailableError
from apps.api.repositories.user_list import PostgresUserListRepository
from apps.api.routers.conftest import make_app

USER_HEADERS = {"X-User-Id": "1"}
OTHER_USER_HEADERS = {"X-User-Id": "2"}


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


async def make_client(sessions, repository=None) -> AsyncClient:
    if repository is None:
        async with sessions.begin() as session:
            session.add_all(
                [
                    UserRow(id=1, name="User 1"),
                    UserRow(id=2, name="User 2"),
                    *[
                        ContentRow(
                            id=content_id,
                            title=f"Content {content_id}",
                            description="",
                        )
                        for content_id in (1, 2, 3)
                    ],
                ]
            )
        repository = PostgresUserListRepository(sessions)
    app = await make_app(
        sessions,
        user_list_repository=repository,
    )
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_create_user_list(sqlalchemy_sessions) -> None:
    async with await make_client(sqlalchemy_sessions) as client:
        response = await client.post(
            "/v1/user-lists", json={"name": "Favorites"}, headers=USER_HEADERS
        )

    assert response.status_code == 201
    assert response.json() == {"id": 1, "user_id": 1, "name": "Favorites"}


async def test_create_user_list_without_user_id_header_returns_400(
    sqlalchemy_sessions,
) -> None:
    async with await make_client(sqlalchemy_sessions) as client:
        response = await client.post("/v1/user-lists", json={"name": "Favorites"})

    assert response.status_code == 400


async def test_create_duplicate_user_list_returns_409(sqlalchemy_sessions) -> None:
    async with await make_client(sqlalchemy_sessions) as client:
        await client.post(
            "/v1/user-lists", json={"name": "Favorites"}, headers=USER_HEADERS
        )
        response = await client.post(
            "/v1/user-lists", json={"name": "Favorites"}, headers=USER_HEADERS
        )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "USER_LIST_ALREADY_EXISTS"


async def test_create_invalid_user_list_returns_400(sqlalchemy_sessions) -> None:
    async with await make_client(sqlalchemy_sessions) as client:
        response = await client.post(
            "/v1/user-lists", json={"name": ""}, headers=USER_HEADERS
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_ARGUMENT"


async def test_retrieve_user_lists_returns_only_the_caller_lists(
    sqlalchemy_sessions,
) -> None:
    async with await make_client(sqlalchemy_sessions) as client:
        await client.post(
            "/v1/user-lists", json={"name": "Favorites"}, headers=USER_HEADERS
        )
        await client.post(
            "/v1/user-lists",
            json={"name": "Someone Else's"},
            headers=OTHER_USER_HEADERS,
        )

        response = await client.get("/v1/user-lists", headers=USER_HEADERS)

    assert response.status_code == 200
    assert [user_list["name"] for user_list in response.json()] == ["Favorites"]


async def test_retrieve_user_lists_defaults_to_most_recent_first(
    sqlalchemy_sessions,
) -> None:
    async with await make_client(sqlalchemy_sessions) as client:
        await client.post(
            "/v1/user-lists", json={"name": "Favorites"}, headers=USER_HEADERS
        )
        await client.post(
            "/v1/user-lists", json={"name": "Watch Later"}, headers=USER_HEADERS
        )

        response = await client.get("/v1/user-lists", headers=USER_HEADERS)

    assert [user_list["name"] for user_list in response.json()] == [
        "Watch Later",
        "Favorites",
    ]


async def test_retrieve_user_lists_supports_cursor_pagination(
    sqlalchemy_sessions,
) -> None:
    async with await make_client(sqlalchemy_sessions) as client:
        await client.post(
            "/v1/user-lists", json={"name": "Favorites"}, headers=USER_HEADERS
        )
        await client.post(
            "/v1/user-lists", json={"name": "Watch Later"}, headers=USER_HEADERS
        )

        first_page = await client.get(
            "/v1/user-lists?page_size=1", headers=USER_HEADERS
        )
        assert [user_list["name"] for user_list in first_page.json()] == ["Watch Later"]
        next_cursor = first_page.headers["X-Next-Cursor"]

        second_page = await client.get(
            f"/v1/user-lists?page_size=1&cursor={next_cursor}", headers=USER_HEADERS
        )
        assert [user_list["name"] for user_list in second_page.json()] == ["Favorites"]

        final_cursor = second_page.headers["X-Next-Cursor"]
        third_page = await client.get(
            f"/v1/user-lists?page_size=1&cursor={final_cursor}", headers=USER_HEADERS
        )

    assert third_page.json() == []


async def test_add_user_list_content(sqlalchemy_sessions) -> None:
    async with await make_client(sqlalchemy_sessions) as client:
        created = await client.post(
            "/v1/user-lists", json={"name": "Favorites"}, headers=USER_HEADERS
        )
        list_id = created.json()["id"]

        response = await client.post(
            f"/v1/user-lists/{list_id}/contents",
            json={"content_id": 1},
            headers=USER_HEADERS,
        )

    assert response.status_code == 201
    assert response.json() == {"id": 1, "user_list_id": list_id, "content_id": 1}


async def test_add_content_to_missing_user_list_returns_404(
    sqlalchemy_sessions,
) -> None:
    async with await make_client(sqlalchemy_sessions) as client:
        response = await client.post(
            "/v1/user-lists/999/contents",
            json={"content_id": 1},
            headers=USER_HEADERS,
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "USER_LIST_NOT_FOUND"


async def test_add_missing_content_returns_404(sqlalchemy_sessions) -> None:
    async with await make_client(sqlalchemy_sessions) as client:
        created = await client.post(
            "/v1/user-lists", json={"name": "Favorites"}, headers=USER_HEADERS
        )
        list_id = created.json()["id"]

        response = await client.post(
            f"/v1/user-lists/{list_id}/contents",
            json={"content_id": 999},
            headers=USER_HEADERS,
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CONTENT_NOT_FOUND"


async def test_add_duplicate_content_returns_409(sqlalchemy_sessions) -> None:
    async with await make_client(sqlalchemy_sessions) as client:
        created = await client.post(
            "/v1/user-lists", json={"name": "Favorites"}, headers=USER_HEADERS
        )
        list_id = created.json()["id"]
        await client.post(
            f"/v1/user-lists/{list_id}/contents",
            json={"content_id": 1},
            headers=USER_HEADERS,
        )

        response = await client.post(
            f"/v1/user-lists/{list_id}/contents",
            json={"content_id": 1},
            headers=USER_HEADERS,
        )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONTENT_ALREADY_IN_LIST"


async def test_remove_user_list_content(sqlalchemy_sessions) -> None:
    async with await make_client(sqlalchemy_sessions) as client:
        created = await client.post(
            "/v1/user-lists", json={"name": "Favorites"}, headers=USER_HEADERS
        )
        list_id = created.json()["id"]
        added = await client.post(
            f"/v1/user-lists/{list_id}/contents",
            json={"content_id": 1},
            headers=USER_HEADERS,
        )
        content_item_id = added.json()["id"]

        response = await client.delete(
            f"/v1/user-lists/{list_id}/contents/{content_item_id}",
            headers=USER_HEADERS,
        )

    assert response.status_code == 204
    assert response.content == b""


async def test_remove_content_not_in_list_returns_404(sqlalchemy_sessions) -> None:
    async with await make_client(sqlalchemy_sessions) as client:
        created = await client.post(
            "/v1/user-lists", json={"name": "Favorites"}, headers=USER_HEADERS
        )
        list_id = created.json()["id"]

        response = await client.delete(
            f"/v1/user-lists/{list_id}/contents/999", headers=USER_HEADERS
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CONTENT_NOT_IN_LIST"


async def test_remove_content_from_missing_user_list_returns_404(
    sqlalchemy_sessions,
) -> None:
    async with await make_client(sqlalchemy_sessions) as client:
        response = await client.delete(
            "/v1/user-lists/999/contents/1", headers=USER_HEADERS
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "USER_LIST_NOT_FOUND"


async def test_repository_failure_returns_503_for_every_endpoint(
    sqlalchemy_sessions,
) -> None:
    async with await make_client(
        sqlalchemy_sessions, UnavailableUserListRepository()
    ) as client:
        create_response = await client.post(
            "/v1/user-lists", json={"name": "Favorites"}, headers=USER_HEADERS
        )
        list_response = await client.get("/v1/user-lists", headers=USER_HEADERS)
        add_response = await client.post(
            "/v1/user-lists/1/contents",
            json={"content_id": 1},
            headers=USER_HEADERS,
        )
        remove_response = await client.delete(
            "/v1/user-lists/1/contents/1", headers=USER_HEADERS
        )

    for response in (create_response, list_response, add_response, remove_response):
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
