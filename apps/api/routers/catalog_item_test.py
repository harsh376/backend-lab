from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from apps.api.routers.conftest import make_app
from backend.db import models
from backend.db.models import CatalogItem as CatalogItemRow

BOOK = {
    "name": "Dune",
    "category": "Science Fiction",
    "item_type": "book",
    "quantity": 3,
}


async def make_client(sessions) -> AsyncClient:
    app = await make_app(sessions)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_create_catalog_item(sqlalchemy_sessions) -> None:
    async with await make_client(sqlalchemy_sessions) as client:
        response = await client.post("/v1/catalog-items", json=BOOK)

    assert response.status_code == 201
    assert response.json() == {"id": 1, **BOOK}


async def test_create_catalog_item_persists_row(sqlalchemy_sessions) -> None:
    async with await make_client(sqlalchemy_sessions) as client:
        response = await client.post("/v1/catalog-items", json=BOOK)

    async with sqlalchemy_sessions() as session:
        row = await session.get(CatalogItemRow, response.json()["id"])

    assert row is not None
    assert row.name == "Dune"
    assert row.category == "Science Fiction"
    assert row.item_type.value == "book"
    assert row.quantity == 3


async def test_create_duplicate_catalog_item_returns_409(sqlalchemy_sessions) -> None:
    async with await make_client(sqlalchemy_sessions) as client:
        await client.post("/v1/catalog-items", json=BOOK)
        response = await client.post("/v1/catalog-items", json={**BOOK, "quantity": 5})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CATALOG_ITEM_ALREADY_EXISTS"


@pytest.mark.parametrize(
    "changes",
    [
        {"name": "Dune Messiah"},
        {"category": "Classics"},
        {"item_type": "movie"},
    ],
)
async def test_create_catalog_item_differing_in_unique_field_succeeds(
    sqlalchemy_sessions, changes
) -> None:
    async with await make_client(sqlalchemy_sessions) as client:
        await client.post("/v1/catalog-items", json=BOOK)
        response = await client.post("/v1/catalog-items", json={**BOOK, **changes})

    assert response.status_code == 201
    assert response.json() == {"id": 2, **BOOK, **changes}


@pytest.mark.parametrize(
    "body",
    [
        {**BOOK, "name": ""},
        {**BOOK, "name": "x" * 201},
        {**BOOK, "category": ""},
        {**BOOK, "category": "x" * 201},
        {**BOOK, "item_type": "magazine"},
        {**BOOK, "quantity": "many"},
        {key: value for key, value in BOOK.items() if key != "quantity"},
        {},
    ],
)
async def test_create_invalid_catalog_item_returns_400(
    sqlalchemy_sessions, body
) -> None:
    async with await make_client(sqlalchemy_sessions) as client:
        response = await client.post("/v1/catalog-items", json=body)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_ARGUMENT"


async def test_create_catalog_item_returns_503_when_database_fails(
    sqlalchemy_sessions,
) -> None:
    async with sqlalchemy_sessions.begin() as session:
        await session.run_sync(
            lambda sync_session: CatalogItemRow.__table__.drop(
                sync_session.connection()
            )
        )

    async with await make_client(sqlalchemy_sessions) as client:
        response = await client.post("/v1/catalog-items", json=BOOK)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"


async def test_get_catalog_items_empty(sqlalchemy_sessions):
    async with await make_client(sqlalchemy_sessions) as client:
        response = await client.get("/v1/catalog-items")
    assert response.status_code == 200
    assert response.json() == []


async def test_get_catalog_items_filters_and_status(sqlalchemy_sessions):
    now = datetime.now(UTC)
    async with sqlalchemy_sessions.begin() as session:
        session.add_all(
            [
                models.CatalogItem(
                    id=1,
                    name="Dune",
                    category="Fiction",
                    item_type=models.CatalogItemType.BOOK,
                    quantity=3,
                ),
                models.CatalogItem(
                    id=2,
                    name="Dune Movie",
                    category="Fiction",
                    item_type=models.CatalogItemType.MOVIE,
                    quantity=0,
                ),
                models.CatalogItem(
                    id=3,
                    name="100% Guide",
                    category="Reference",
                    item_type=models.CatalogItemType.BOOK,
                    quantity=2,
                ),
            ]
        )
        session.add_all([models.Patron(id=i, name=f"Patron {i}") for i in range(1, 7)])
        await session.flush()
        session.add_all(
            [
                models.Reservation(
                    catalog_item_id=1,
                    patron_id=1,
                    status=models.ReservationStatus.ACTIVE,
                ),
                models.Reservation(
                    catalog_item_id=1,
                    patron_id=2,
                    status=models.ReservationStatus.CANCELLED,
                ),
                models.Hold(
                    catalog_item_id=1,
                    patron_id=3,
                    status=models.HoldStatus.ALLOCATED,
                    expires_at=now + timedelta(days=1),
                ),
                models.Hold(
                    catalog_item_id=1,
                    patron_id=4,
                    status=models.HoldStatus.ALLOCATED,
                    expires_at=now - timedelta(days=1),
                ),
                models.Hold(
                    catalog_item_id=1,
                    patron_id=5,
                    status=models.HoldStatus.CANCELLED,
                    expires_at=now + timedelta(days=1),
                ),
                models.Hold(
                    catalog_item_id=1,
                    patron_id=6,
                    status=models.HoldStatus.EXPIRED,
                    expires_at=now + timedelta(days=1),
                ),
            ]
        )
    async with await make_client(sqlalchemy_sessions) as client:
        response = await client.get("/v1/catalog-items")
        assert response.status_code == 200
        assert [(r["id"], r["item_status"]) for r in response.json()] == [
            (1, "available"),
            (2, "not_available"),
            (3, "available"),
        ]
        assert all("availability" not in r for r in response.json())
        for params, expected in [
            ({"item_status": "available"}, [1, 3]),
            ({"item_status": "not_available"}, [2]),
            ({"item_type": "movie"}, [2]),
            ({"search_query": "Dune"}, [1, 2]),
            ({"search_query": "dune"}, [1, 2]),
            ({"search_query": "%"}, [3]),
            (
                {
                    "search_query": "Dune",
                    "item_type": "book",
                    "item_status": "available",
                },
                [1],
            ),
        ]:
            response = await client.get("/v1/catalog-items", params=params)
            assert response.status_code == 200
            assert [r["id"] for r in response.json()] == expected


async def test_get_catalog_items_database_failure(sqlalchemy_sessions):
    async with sqlalchemy_sessions.begin() as session:
        await session.run_sync(
            lambda sync_session: CatalogItemRow.__table__.drop(
                sync_session.connection()
            )
        )
    async with await make_client(sqlalchemy_sessions) as client:
        response = await client.get("/v1/catalog-items")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"


class TestCreateCatalogItemReservation:
    async def test_missing_item_raises_404(self, sqlalchemy_sessions):
        async with await make_client(sqlalchemy_sessions) as client:
            response = await client.post(
                url="/v1/catalog-items/123/reservations",
                json={
                    "patron_id": 1,
                },
            )
            assert response.status_code == 404
            assert response.json()["error"]["code"] == "CATALOG_ITEM_NOT_FOUND"

    async def test_missing_patron_raises_404(self, sqlalchemy_sessions):
        async with sqlalchemy_sessions.begin() as session:
            session.add(
                models.CatalogItem(
                    id=1,
                    **{**BOOK, "quantity": 1, "item_type": models.CatalogItemType.BOOK},
                )
            )

        async with await make_client(sqlalchemy_sessions) as client:
            response = await client.post(
                url="/v1/catalog-items/1/reservations",
                json={
                    "patron_id": 1,
                },
            )
            assert response.status_code == 404
            assert response.json()["error"]["code"] == "PATRON_NOT_FOUND"

    async def test_unavailable_item_raises_409(self, sqlalchemy_sessions):
        async with sqlalchemy_sessions.begin() as session:
            session.add(
                models.CatalogItem(
                    id=1,
                    **{**BOOK, "quantity": 0, "item_type": models.CatalogItemType.BOOK},
                )
            )
            session.add(models.Patron(id=1, name="Patron1"))

        async with await make_client(sqlalchemy_sessions) as client:
            response = await client.post(
                url="/v1/catalog-items/1/reservations",
                json={
                    "patron_id": 1,
                },
            )
            assert response.status_code == 409
            assert response.json()["error"]["code"] == "CATALOG_ITEM_NOT_AVAILABLE"

    async def test_reservation_created_successfully(self, sqlalchemy_sessions):
        async with sqlalchemy_sessions.begin() as session:
            session.add(
                models.CatalogItem(
                    id=1,
                    **{**BOOK, "quantity": 2, "item_type": models.CatalogItemType.BOOK},
                )
            )
            session.add(models.Patron(id=1, name="Patron1"))

        async with await make_client(sqlalchemy_sessions) as client:
            response = await client.post(
                url="/v1/catalog-items/1/reservations",
                json={
                    "patron_id": 1,
                },
            )
            assert response.status_code == 201
            assert response.json() == {
                "catalog_item_id": 1,
                "id": 1,
                "patron_id": 1,
                "status": "active",
            }

            response = await client.post(
                url="/v1/catalog-items/1/reservations",
                json={
                    "patron_id": 1,
                },
            )
            assert response.status_code == 409
            assert response.json()["error"]["code"] == "RESERVATION_ALREADY_EXISTS"
