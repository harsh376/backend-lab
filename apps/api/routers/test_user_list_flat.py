import logging

from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from apps.api.routers.conftest import make_app
from backend.db.models import User as UserRow
from backend.repositories.user_list import PostgresUserListRepository

USER_HEADERS = {"X-User-Id": "1"}


async def make_client(
    sessions: async_sessionmaker[AsyncSession],
    *,
    seed_user: bool = True,
) -> AsyncClient:
    if seed_user:
        async with sessions.begin() as session:
            session.add(UserRow(id=1, name="Test User"))

    repository = PostgresUserListRepository(sessions)
    app = await make_app(
        user_list_repository=repository,
        database_sessions=sessions,
    )
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_create_user_list_flat_matches_create_user_list(
    sqlalchemy_sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with await make_client(sqlalchemy_sessions) as client:
        response = await client.post(
            "/v1/user-lists-flat",
            json={"name": "Favorites"},
            headers=USER_HEADERS,
        )
        persisted = await client.get("/v1/user-lists", headers=USER_HEADERS)

    assert response.status_code == 201
    assert response.json() == {"id": 1, "user_id": 1, "name": "Favorites"}
    assert persisted.json() == [response.json()]


async def test_create_user_list_flat_validates_the_request(
    sqlalchemy_sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with await make_client(sqlalchemy_sessions) as client:
        response = await client.post(
            "/v1/user-lists-flat", json={"name": ""}, headers=USER_HEADERS
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_ARGUMENT"


async def test_create_user_list_flat_returns_404_for_missing_user(
    sqlalchemy_sessions: async_sessionmaker[AsyncSession],
    caplog,
) -> None:
    caplog.set_level(logging.WARNING)
    async with await make_client(sqlalchemy_sessions, seed_user=False) as client:
        response = await client.post(
            "/v1/user-lists-flat",
            json={"name": "Favorites"},
            headers=USER_HEADERS,
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "USER_NOT_FOUND"
    assert "user_list_flat_user_not_found" in caplog.messages


async def test_create_user_list_flat_returns_409_for_duplicate_name(
    sqlalchemy_sessions: async_sessionmaker[AsyncSession],
    caplog,
) -> None:
    caplog.set_level(logging.WARNING)
    async with await make_client(sqlalchemy_sessions) as client:
        await client.post(
            "/v1/user-lists-flat",
            json={"name": "Favorites"},
            headers=USER_HEADERS,
        )
        response = await client.post(
            "/v1/user-lists-flat",
            json={"name": "Favorites"},
            headers=USER_HEADERS,
        )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "USER_LIST_ALREADY_EXISTS"
    assert "user_list_flat_already_exists" in caplog.messages


async def test_create_user_list_flat_returns_503_for_database_failure(
    sqlalchemy_sessions: async_sessionmaker[AsyncSession],
    monkeypatch,
    caplog,
) -> None:
    client = await make_client(sqlalchemy_sessions)

    async def raise_database_error(*args, **kwargs):
        raise SQLAlchemyError("database unavailable")

    monkeypatch.setattr(AsyncSession, "scalar", raise_database_error)
    caplog.set_level(logging.ERROR)
    async with client:
        response = await client.post(
            "/v1/user-lists-flat",
            json={"name": "Favorites"},
            headers=USER_HEADERS,
        )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
    assert "user_list_flat_database_error" in caplog.messages
