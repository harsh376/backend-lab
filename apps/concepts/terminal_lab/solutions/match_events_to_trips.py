import asyncio
import bisect
import datetime
from collections import defaultdict
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

    async def get_trips(
        self, vehicle_ids: list[VehicleID] | None = None
    ) -> dict[VehicleID, list[Trip]]:
        params = {}
        if vehicle_ids:
            params["vehicleIDs"] = ",".join(vehicle_ids)

        response = await self.fetch(
            url=f"{self.api_base_url}/v1/trips",
            params=params,
        )
        trips = defaultdict(list)
        for t in response["results"]:
            parsed_trip = Trip.model_validate(t)
            trips[parsed_trip.vehicle_id].append(parsed_trip)
        return trips

    async def get_events(
        self, vehicle_ids: list[VehicleID] | None = None
    ) -> dict[VehicleID, list[Event]]:
        params = {}
        if vehicle_ids:
            params["vehicleIDs"] = ",".join(vehicle_ids)

        response = await self.fetch(
            url=f"{self.api_base_url}/v1/events",
            params=params,
        )
        events: dict[VehicleID, list[Event]] = defaultdict(list)
        for e in response["results"]:
            parsed_event = Event.model_validate(e)
            bisect.insort_right(
                a=events[parsed_event.vehicle_id],
                x=parsed_event,
                key=lambda e: e.occurred_at,
            )
        return events

    async def get_report(
        self, vehicle_ids: list[VehicleID] | None = None
    ) -> dict[VehicleID, list[Trip]]:
        async with asyncio.TaskGroup() as tg:
            task_trips = tg.create_task(self.get_trips(vehicle_ids=vehicle_ids))
            task_events = tg.create_task(self.get_events(vehicle_ids=vehicle_ids))

        trips = task_trips.result()
        events = task_events.result()

        report = defaultdict(list)
        for vehicle_id in trips:
            vehicle_trips = trips[vehicle_id]
            vehicle_events = events[vehicle_id]
            event_times = [e.occurred_at for e in vehicle_events]
            for t in vehicle_trips:
                left = bisect.bisect_left(a=event_times, x=t.started_at)
                right = bisect.bisect_right(
                    a=event_times,
                    x=t.ended_at,
                )
                trip_events = vehicle_events[left:right]
                report[vehicle_id].append(t.model_copy(update={"events": trip_events}))
        return report
