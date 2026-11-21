import asyncio
import datetime
import logging
import os
from typing import Annotated

import httpx
import tenacity
from pydantic import AfterValidator, AwareDatetime, BaseModel

type VehicleID = str
type EventID = str


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class RateLimitException(Exception):
    def __init__(self, response: httpx.Response):
        self.response = response


UTCDatetime = Annotated[
    AwareDatetime,
    AfterValidator(lambda dt: datetime.datetime.astimezone(dt, datetime.UTC)),
]


class Event(BaseModel):
    vehicle_id: str
    event_id: str
    started_at: UTCDatetime


def date_to_str(d: datetime.datetime) -> str:
    return (
        d.astimezone(tz=datetime.UTC)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def str_to_date(d: str) -> datetime.datetime:
    d1 = datetime.datetime.fromisoformat(d)
    if d1.tzinfo is None:
        raise Exception("tzinfo not provided")
    return d1.astimezone(datetime.UTC)


def parse_retry_after(now: datetime.datetime, raw: str) -> float:
    try:
        return float(raw)
    except ValueError:
        pass

    dt = str_to_date(raw)
    delta = (dt - now.astimezone(tz=datetime.UTC)).total_seconds()
    return max(0, delta)


def _wait(retry_state: tenacity.RetryCallState) -> float | int:
    exc = retry_state.outcome.exception()

    if isinstance(exc, RateLimitException):
        response_headers = exc.response.headers
        retry_after = response_headers.get("Retry-After")
        if retry_after is None:
            return 0

        return parse_retry_after(
            now=datetime.datetime.now(),
            raw=retry_after,
        )
    return tenacity.wait_exponential(multiplier=1, min=1, max=60)(retry_state)


class Service:
    def __init__(
        self,
        client: httpx.AsyncClient,
        api_base_url: str = "https://api.sandbox.withterminal.com",
    ):
        self.client = client
        self.api_base_url = api_base_url

    async def fetch(self, url: str, params: dict | None = None) -> dict:
        @tenacity.retry(
            wait=_wait,
            stop=tenacity.stop_after_attempt(max_attempt_number=3),
            retry=tenacity.retry_if_exception_type(RateLimitException),
            reraise=True,
        )
        async def _attempt():
            response = await self.client.get(url=url, params=params)
            if response.status_code in {429}:
                raise RateLimitException(response=response)
            response.raise_for_status()
            return response.json()

        return await _attempt()

    async def paginate(self, url: str, params: dict | None = None):
        response = await self.fetch(url, params)
        results = response["results"]
        cursor = response.get("next")

        seen_cursors = set()
        while cursor and cursor not in seen_cursors:
            response = await self.fetch(
                url=url,
                params={
                    **params,
                    "cursor": cursor,
                },
            )
            results += response["results"]
            seen_cursors.add(cursor)
            cursor = response.get("next")
        return results

    async def get_latest_events(
        self, vehicle_ids: list[str], cutoff: str
    ) -> dict[VehicleID, Event]:
        results = await self.paginate(
            url=f"{self.api_base_url}/events",
            params={
                "vehicleIDs": vehicle_ids,
                "limit": 10,
                "startedBefore": cutoff,
            },
        )
        events = [Event(**r) for r in results]
        latest_event_by_vehicle: dict[VehicleID, Event] = {}
        for event in events:
            vehicle_id = event.vehicle_id
            prev = latest_event_by_vehicle.get(vehicle_id)
            if prev is None or event.started_at > prev.started_at:
                latest_event_by_vehicle[vehicle_id] = event
        return latest_event_by_vehicle


async def main():
    api_secret_key = os.environ["API_SECRET_KEY"]
    connection_token = os.environ["CONNECTION_TOKEN"]

    async with httpx.AsyncClient(
        headers={
            "Authorization": f"Bearer {api_secret_key}",
            "Connection-Token": connection_token,
        }
    ) as client:
        service = Service(
            client=client,
        )
        await service.get_latest_events(
            vehicle_ids=["v1", "v2"],
            cutoff="2026-11-20T15:21:00.000Z",
        )


if __name__ == "__main__":
    asyncio.run(main())
