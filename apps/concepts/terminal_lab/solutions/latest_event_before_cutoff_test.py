import datetime

import httpx
import pytest
from httpx import MockTransport

from apps.concepts.terminal_lab.solutions.latest_event_before_cutoff import (
    Event,
    Service,
    parse_retry_after,
)


async def basic_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/events":
        return httpx.Response(
            200,
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
                    {
                        "vehicle_id": "v2",
                        "event_id": "e3",
                        "started_at": "2026-11-20T15:22:00.000Z",
                    },
                ]
            },
        )


async def test_correct_latest_events_by_vehicle():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(basic_handler)
    ) as client:
        service = Service(client=client)
        result = await service.get_latest_events(
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


async def test_fetch_error_raises_on_400():
    def handler_400(request: httpx.Request):
        return httpx.Response(status_code=400)

    async with httpx.AsyncClient(transport=MockTransport(handler_400)) as client:
        service = Service(client=client)
        with pytest.raises(httpx.HTTPStatusError):
            await service.get_latest_events(
                vehicle_ids=["v1", "v2"],
                cutoff="2026-11-20T15:24:54.000Z",
            )


async def test_fetch_error_retries_on_429():
    call_count = 0

    def rate_limiting_handler(request: httpx.Request):
        nonlocal call_count
        responses = [
            httpx.Response(
                headers={
                    "Retry-After": "0",
                },
                status_code=429,
            ),
            httpx.Response(
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
                status_code=200,
            ),
        ]
        response = responses[call_count]
        call_count += 1
        return response

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(rate_limiting_handler)
    ) as client:
        service = Service(client=client)
        result = await service.get_latest_events(
            vehicle_ids=["v1", "v2"], cutoff="2026-11-20T15:24:54.000Z"
        )

        assert call_count == 2
        assert result == {
            "v1": Event(
                vehicle_id="v1",
                event_id="e2",
                started_at=datetime.datetime(2026, 11, 20, 15, 21, tzinfo=datetime.UTC),
            )
        }


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
