import datetime
from collections import Counter

import httpx
import pytest
from httpx import MockTransport

from apps.concepts.terminal_lab.solutions.latest_event_before_cutoff import (
    Event,
    Service,
    parse_retry_after,
)


async def test_correct_latest_events_by_vehicle():
    async def basic_handler(request: httpx.Request) -> httpx.Response:
        events = [
            {
                "vehicle_id": "v1",
                "event_id": "e1",
                "started_at": "2026-11-20T15:20:54.000Z",
            },
            {
                "vehicle_id": "v1",
                "event_id": "e2",
                "started_at": "2026-11-20T15:21:00.000Z",
            },
            {
                "vehicle_id": "v2",
                "event_id": "e3",
                "started_at": "2026-11-20T15:22:00.000Z",
            },
        ]
        vehicle_ids = request.url.params.get("vehicleIDs").split(",")
        results = {
            "results": list(
                filter(lambda event: event["vehicle_id"] in vehicle_ids, events)
            )
        }
        return httpx.Response(
            200,
            json=results,
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(basic_handler)
    ) as client:
        service = Service(client=client)
        result, _ = await service.get_latest_events(
            vehicle_ids=["v1", "v2"], cutoff="2026-11-20T15:24:54.000Z"
        )
        assert result == {
            "v1": Event(
                vehicle_id="v1",
                event_id="e2",
                started_at=datetime.datetime(2026, 11, 20, 15, 21, tzinfo=datetime.UTC),
            ),
            "v2": Event(
                vehicle_id="v2",
                event_id="e3",
                started_at=datetime.datetime(2026, 11, 20, 15, 22, tzinfo=datetime.UTC),
            ),
        }


async def test_fetch_error():
    def handler_400(request: httpx.Request):
        if "v2" in request.url.params.get("vehicleIDs"):
            return httpx.Response(status_code=400)
        return httpx.Response(
            status_code=200,
            json={
                "results": [
                    {
                        "vehicle_id": "v1",
                        "event_id": "e1",
                        "started_at": "2026-11-20T15:20:54.000Z",
                    },
                    {
                        "vehicle_id": "v1",
                        "event_id": "e2",
                        "started_at": "2026-11-20T15:21:00.000Z",
                    },
                ]
            },
        )

    async with httpx.AsyncClient(transport=MockTransport(handler_400)) as client:
        service = Service(client=client)
        results, errors = await service.get_latest_events(
            vehicle_ids=["v1", "v2"],
            cutoff="2026-11-20T15:24:54.000Z",
        )
        assert results == {
            "v1": Event(
                vehicle_id="v1",
                event_id="e2",
                started_at=datetime.datetime(2026, 11, 20, 15, 21, tzinfo=datetime.UTC),
            )
        }
        assert errors == ["v2"]


async def test_fetch_error_retries_on_429():
    call_count = Counter()

    def rate_limiting_handler(request: httpx.Request):
        nonlocal call_count
        events = [
            {
                "vehicle_id": "v1",
                "event_id": "e1",
                "started_at": "2026-11-20T15:20:54.000Z",
            },
            {
                "vehicle_id": "v1",
                "event_id": "e2",
                "started_at": "2026-11-20T15:21:00.000Z",
            },
        ]
        vehicle_ids_raw = request.url.params.get("vehicleIDs")
        vehicle_ids = vehicle_ids_raw.split(",")
        results = list(filter(lambda event: event["vehicle_id"] in vehicle_ids, events))
        responses = [
            httpx.Response(
                headers={
                    "Retry-After": "0",
                },
                status_code=429,
            ),
            httpx.Response(
                json={"results": results},
                status_code=200,
            ),
        ]
        response = responses[call_count[vehicle_ids_raw]]
        call_count[vehicle_ids_raw] += 1
        return response

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(rate_limiting_handler)
    ) as client:
        service = Service(client=client)
        result, errors = await service.get_latest_events(
            vehicle_ids=["v1", "v2"], cutoff="2026-11-20T15:24:54.000Z"
        )

        assert call_count == Counter({"v1": 2, "v2": 2})
        assert result == {
            "v1": Event(
                vehicle_id="v1",
                event_id="e2",
                started_at=datetime.datetime(2026, 11, 20, 15, 21, tzinfo=datetime.UTC),
            ),
        }
        assert errors == []


@pytest.mark.parametrize(
    "now, raw, expected",
    [
        ("2026-11-20T15:21:00.000Z", "20", 20),
        ("2026-11-20T15:21:00.000Z", "2026-11-20T15:21:10.000Z", 10),
    ],
)
def test_parse_retry_after(now: str, raw: str, expected: float):
    now = datetime.datetime.fromisoformat(now)
    assert (
        parse_retry_after(
            now=now,
            raw=raw,
        )
        == expected
    )


async def test_correct_latest_events_when_multiple_pages():
    page_size = 1
    call_count = Counter()
    events = [
        {
            "vehicle_id": "v1",
            "event_id": "e1",
            "started_at": "2026-11-20T15:20:50.000Z",
        },
        {
            "vehicle_id": "v2",
            "event_id": "e2",
            "started_at": "2026-11-20T15:20:55.000Z",
        },
        {
            "vehicle_id": "v1",
            "event_id": "e3",
            "started_at": "2026-11-20T15:20:52.000Z",
        },
        {
            "vehicle_id": "v2",
            "event_id": "e4",
            "started_at": "2026-11-20T15:20:50.000Z",
        },
        {
            "vehicle_id": "v3",
            "event_id": "e5",
            "started_at": "2026-11-20T15:20:52.000Z",
        },
    ]

    def paginate_handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count

        vehicle_ids_raw = request.url.params.get("vehicleIDs")
        vehicle_ids = vehicle_ids_raw.split(",")
        vehicle_events = list(
            filter(lambda event: event["vehicle_id"] in vehicle_ids, events)
        )

        cursor = int(request.url.params.get("cursor", 0))
        limit = int(request.url.params["limit"])
        response_body = {
            "results": vehicle_events[cursor : cursor + limit],
        }
        if vehicle_events[cursor + limit :]:
            response_body["next"] = str(cursor + limit)

        response = httpx.Response(
            status_code=200,
            json=response_body,
        )
        call_count[vehicle_ids_raw] += 1
        return response

    async with httpx.AsyncClient(transport=MockTransport(paginate_handler)) as client:
        service = Service(client=client, page_size=page_size)
        result, _ = await service.get_latest_events(
            vehicle_ids=["v1", "v2", "v3"],
            cutoff="2026-11-20T15:21:00.000Z",
        )
        assert call_count == Counter({"v1": 2, "v2": 2, "v3": 1})
        assert result == {
            "v1": Event(
                vehicle_id="v1",
                event_id="e3",
                started_at=datetime.datetime(
                    2026, 11, 20, 15, 20, 52, tzinfo=datetime.UTC
                ),
            ),
            "v2": Event(
                vehicle_id="v2",
                event_id="e2",
                started_at=datetime.datetime(
                    2026, 11, 20, 15, 20, 55, tzinfo=datetime.UTC
                ),
            ),
            "v3": Event(
                vehicle_id="v3",
                event_id="e5",
                started_at=datetime.datetime(
                    2026, 11, 20, 15, 20, 52, tzinfo=datetime.UTC
                ),
            ),
        }
