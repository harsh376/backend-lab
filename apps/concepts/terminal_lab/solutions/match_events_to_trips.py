import asyncio
import bisect
import datetime
from typing import Annotated

import httpx
import tenacity
from pydantic import AfterValidator, AwareDatetime, BaseModel

UTCDatetime = Annotated[
    AwareDatetime,
    AfterValidator(lambda dt: datetime.datetime.astimezone(dt, tz=datetime.UTC)),
]

type TripID = str
type VehicleID = str
type EventID = str


class Event(BaseModel):
    event_id: EventID
    vehicle_id: VehicleID
    occurred_at: UTCDatetime


class Trip(BaseModel):
    trip_id: TripID
    vehicle_id: VehicleID
    started_at: UTCDatetime
    ended_at: UTCDatetime
    events: list[Event] | None = None


class Service:
    def __init__(
        self,
        client: httpx.AsyncClient,
        api_base_url: str = "https://api.sandbox.withterminal.com",
    ):
        self.client = client
        self.api_base_url = api_base_url

    async def fetch(self, url: str, params: dict | None = None):
        params = dict(params or {})

        @tenacity.retry(
            wait=tenacity.wait_exponential(multiplier=1, min=1, max=60),
            stop=tenacity.stop_after_attempt(max_attempt_number=5),
            reraise=True,
        )
        async def _attempt():
            response = await self.client.get(url=url, params=params)
            response.raise_for_status()
            return response.json()

        return await _attempt()

    async def get_trips_by_vehicle(self, vehicle_id: str) -> list[Trip]:
        response = await self.fetch(
            url=f"{self.api_base_url}/v1/trips", params={"vehicleIDs": vehicle_id}
        )
        trips = [Trip.model_validate(t) for t in response["results"]]
        return trips

    async def get_events_by_vehicle(self, vehicle_id: str) -> list[Event]:
        response = await self.fetch(
            url=f"{self.api_base_url}/v1/events", params={"vehicleIDs": vehicle_id}
        )
        events = [Event.model_validate(t) for t in response["results"]]
        sorted_events = sorted(events, key=lambda e: e.occurred_at)
        return sorted_events

    async def get_report(self, vehicle_id: VehicleID) -> list[Trip]:
        async with asyncio.TaskGroup() as tg:
            task_trips = tg.create_task(
                self.get_trips_by_vehicle(vehicle_id=vehicle_id)
            )
            task_events = tg.create_task(
                self.get_events_by_vehicle(vehicle_id=vehicle_id)
            )

        trips = task_trips.result()
        events = task_events.result()
        event_times = [e.occurred_at for e in events]

        enhanced_trips = []
        for trip in trips:
            left = bisect.bisect_left(a=event_times, x=trip.started_at)
            right = bisect.bisect_right(
                a=event_times,
                x=trip.ended_at,
            )
            trip_events = events[left:right]
            enhanced_trip = trip.model_copy(update={"events": trip_events})
            enhanced_trips.append(enhanced_trip)
        return enhanced_trips
