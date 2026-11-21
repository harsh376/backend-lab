import datetime

import httpx
import pytest
from httpx import MockTransport

from apps.concepts.terminal_lab.solutions.match_events_to_trips import (
    Event,
    Service,
    Trip,
)

MOCK_TRIPS = [
    {
        "trip_id": "t1",
        "vehicle_id": "v1",
        "started_at": "2026-01-01T10:00:00.000Z",
        "ended_at": "2026-01-02T11:00:00.000Z",
    },
    {
        "trip_id": "t2",
        "vehicle_id": "v1",
        "started_at": "2026-01-03T10:00:00.000Z",
        "ended_at": "2026-01-04T12:00:00.000Z",
    },
    {
        "trip_id": "t3",
        "vehicle_id": "v2",
        "started_at": "2026-01-03T10:00:00.000Z",
        "ended_at": "2026-01-04T12:00:00.000Z",
    },
]
MOCK_EVENTS = [
    {
        "event_id": "e1",
        "vehicle_id": "v1",
        "occurred_at": "2026-01-01T10:10:00.000Z",
    },
    {
        "event_id": "e2",
        "vehicle_id": "v1",
        "occurred_at": "2026-01-01T10:20:00.000Z",
    },
    {
        "event_id": "e3",
        "vehicle_id": "v2",
        "occurred_at": "2026-01-03T10:00:00.000Z",
    },
    {
        "event_id": "e4",
        "vehicle_id": "v2",
        "occurred_at": "2026-01-03T10:01:00.000Z",
    },
    {
        "event_id": "e5",
        "vehicle_id": "v2",
        "occurred_at": "2026-01-04T12:00:00.000Z",
    },
]


async def test_get_trips():
    def handle(request: httpx.Request) -> httpx.Response:
        vehicle_ids_raw = request.url.params.get("vehicleIDs")
        vehicle_ids = vehicle_ids_raw.split(",")
        trips = list(filter(lambda t: t["vehicle_id"] in vehicle_ids, MOCK_TRIPS))
        return httpx.Response(
            status_code=200,
            json={
                "results": trips,
            },
        )

    async with httpx.AsyncClient(transport=MockTransport(handle)) as client:
        service = Service(
            client=client,
        )
        results = await service.get_trips(vehicle_ids=["v1"])
        assert results == {
            "v1": [
                Trip(
                    trip_id="t1",
                    vehicle_id="v1",
                    started_at=datetime.datetime(
                        2026, 1, 1, 10, 0, tzinfo=datetime.UTC
                    ),
                    ended_at=datetime.datetime(2026, 1, 2, 11, 0, tzinfo=datetime.UTC),
                ),
                Trip(
                    trip_id="t2",
                    vehicle_id="v1",
                    started_at=datetime.datetime(
                        2026, 1, 3, 10, 0, tzinfo=datetime.UTC
                    ),
                    ended_at=datetime.datetime(2026, 1, 4, 12, 0, tzinfo=datetime.UTC),
                ),
            ]
        }


@pytest.mark.parametrize(
    "vehicle_ids, expected",
    [
        (
            ["v1"],
            {
                "v1": [
                    Event(
                        event_id="e1",
                        vehicle_id="v1",
                        occurred_at=datetime.datetime(
                            2026, 1, 1, 10, 10, tzinfo=datetime.UTC
                        ),
                    ),
                    Event(
                        event_id="e2",
                        vehicle_id="v1",
                        occurred_at=datetime.datetime(
                            2026, 1, 1, 10, 20, tzinfo=datetime.UTC
                        ),
                    ),
                ]
            },
        ),
        (
            ["v2"],
            {
                "v2": [
                    Event(
                        event_id="e3",
                        vehicle_id="v2",
                        occurred_at=datetime.datetime(
                            2026, 1, 3, 10, 0, tzinfo=datetime.UTC
                        ),
                    ),
                    Event(
                        event_id="e4",
                        vehicle_id="v2",
                        occurred_at=datetime.datetime(
                            2026, 1, 3, 10, 1, tzinfo=datetime.UTC
                        ),
                    ),
                    Event(
                        event_id="e5",
                        vehicle_id="v2",
                        occurred_at=datetime.datetime(
                            2026, 1, 4, 12, 0, tzinfo=datetime.UTC
                        ),
                    ),
                ]
            },
        ),
    ],
)
async def test_get_events(vehicle_ids, expected):
    def handle(request: httpx.Request) -> httpx.Response:
        vehicle_ids_raw = request.url.params.get("vehicleIDs")
        v_ids = vehicle_ids_raw.split(",")
        events = list(filter(lambda t: t["vehicle_id"] in v_ids, MOCK_EVENTS))
        return httpx.Response(
            status_code=200,
            json={
                "results": events,
            },
        )

    async with httpx.AsyncClient(transport=MockTransport(handle)) as client:
        service = Service(client=client)
        results = await service.get_events(vehicle_ids=vehicle_ids)
        assert results == expected


@pytest.mark.parametrize(
    "vehicle_ids, expected",
    [
        (
            ["v1"],
            {
                "v1": [
                    Trip(
                        trip_id="t1",
                        vehicle_id="v1",
                        started_at=datetime.datetime(
                            2026, 1, 1, 10, 0, tzinfo=datetime.UTC
                        ),
                        ended_at=datetime.datetime(
                            2026, 1, 2, 11, 0, tzinfo=datetime.UTC
                        ),
                        events=[
                            Event(
                                event_id="e1",
                                vehicle_id="v1",
                                occurred_at=datetime.datetime(
                                    2026, 1, 1, 10, 10, tzinfo=datetime.UTC
                                ),
                            ),
                            Event(
                                event_id="e2",
                                vehicle_id="v1",
                                occurred_at=datetime.datetime(
                                    2026, 1, 1, 10, 20, tzinfo=datetime.UTC
                                ),
                            ),
                        ],
                    ),
                    Trip(
                        trip_id="t2",
                        vehicle_id="v1",
                        started_at=datetime.datetime(
                            2026, 1, 3, 10, 0, tzinfo=datetime.UTC
                        ),
                        ended_at=datetime.datetime(
                            2026, 1, 4, 12, 0, tzinfo=datetime.UTC
                        ),
                        events=[],
                    ),
                ]
            },
        ),
        (
            ["v1", "v2"],
            {
                "v1": [
                    Trip(
                        trip_id="t1",
                        vehicle_id="v1",
                        started_at=datetime.datetime(
                            2026, 1, 1, 10, 0, tzinfo=datetime.UTC
                        ),
                        ended_at=datetime.datetime(
                            2026, 1, 2, 11, 0, tzinfo=datetime.UTC
                        ),
                        events=[
                            Event(
                                event_id="e1",
                                vehicle_id="v1",
                                occurred_at=datetime.datetime(
                                    2026, 1, 1, 10, 10, tzinfo=datetime.UTC
                                ),
                            ),
                            Event(
                                event_id="e2",
                                vehicle_id="v1",
                                occurred_at=datetime.datetime(
                                    2026, 1, 1, 10, 20, tzinfo=datetime.UTC
                                ),
                            ),
                        ],
                    ),
                    Trip(
                        trip_id="t2",
                        vehicle_id="v1",
                        started_at=datetime.datetime(
                            2026, 1, 3, 10, 0, tzinfo=datetime.UTC
                        ),
                        ended_at=datetime.datetime(
                            2026, 1, 4, 12, 0, tzinfo=datetime.UTC
                        ),
                        events=[],
                    ),
                ],
                "v2": [
                    Trip(
                        trip_id="t3",
                        vehicle_id="v2",
                        started_at=datetime.datetime(
                            2026, 1, 3, 10, 0, tzinfo=datetime.UTC
                        ),
                        ended_at=datetime.datetime(
                            2026, 1, 4, 12, 0, tzinfo=datetime.UTC
                        ),
                        events=[
                            Event(
                                event_id="e3",
                                vehicle_id="v2",
                                occurred_at=datetime.datetime(
                                    2026, 1, 3, 10, 0, tzinfo=datetime.UTC
                                ),
                            ),
                            Event(
                                event_id="e4",
                                vehicle_id="v2",
                                occurred_at=datetime.datetime(
                                    2026, 1, 3, 10, 1, tzinfo=datetime.UTC
                                ),
                            ),
                            Event(
                                event_id="e5",
                                vehicle_id="v2",
                                occurred_at=datetime.datetime(
                                    2026, 1, 4, 12, 0, tzinfo=datetime.UTC
                                ),
                            ),
                        ],
                    )
                ],
            },
        ),
    ],
)
async def test_get_report(vehicle_ids, expected):
    def handle(request: httpx.Request) -> httpx.Response:
        vehicle_ids_raw = request.url.params.get("vehicleIDs")
        v_ids = vehicle_ids_raw.split(",")
        if request.url.path == "/v1/trips":
            trips = list(filter(lambda t: t["vehicle_id"] in v_ids, MOCK_TRIPS))
            return httpx.Response(
                status_code=200,
                json={
                    "results": trips,
                },
            )
        elif request.url.path == "/v1/events":
            events = list(filter(lambda t: t["vehicle_id"] in v_ids, MOCK_EVENTS))
            return httpx.Response(
                status_code=200,
                json={
                    "results": events,
                },
            )
        return httpx.Response(
            status_code=400,
        )

    async with httpx.AsyncClient(transport=MockTransport(handle)) as client:
        service = Service(client=client)
        report = await service.get_report(vehicle_ids=vehicle_ids)
        assert report == expected
