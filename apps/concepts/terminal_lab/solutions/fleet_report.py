import asyncio
import datetime
import os
from typing import Annotated

import httpx
from pydantic import AfterValidator, AwareDatetime, BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

# Normalized to UTC on validation; pydantic serializes UTC as "...Z".
UtcDatetime = Annotated[
    AwareDatetime, AfterValidator(lambda dt: dt.astimezone(datetime.UTC))
]


class TerminalModel(BaseModel):
    # Terminal uses camelCase on the wire; fields are snake_case here.
    model_config = ConfigDict(alias_generator=to_camel, validate_by_name=True)


class ErrorResponseBody(TerminalModel):
    code: str
    message: str
    retry_after: int | None = None
    detail: str | list[dict] | None = None


class Metadata(TerminalModel):
    modified_at: AwareDatetime
    added_at: AwareDatetime | None = None
    visibility: str | None = None
    deleted_at: AwareDatetime | None = None


class Vehicle(TerminalModel):
    id: str
    vin: str
    provider: str
    status: str
    groups: list[str]
    devices: list[str]
    metadata: Metadata


class Driver(TerminalModel):
    id: str
    source_id: str
    provider: str
    status: str
    email: str
    license: dict
    groups: list[str]
    metadata: Metadata


class Location(TerminalModel):
    latitude: float
    longitude: float


class RealTimeVehicleLatestLocation(TerminalModel):
    provider: str
    vehicle: str
    driver: str
    odometer: float
    located_at: AwareDatetime
    address: dict
    location: Location
    metadata: Metadata


class HistoricalVehicleLocation(TerminalModel):
    id: str
    provider: str
    vehicle: str
    driver: str
    location: Location
    located_at: AwareDatetime
    address: dict
    metadata: Metadata


class HistoricalTrip(TerminalModel):
    id: str
    source_id: str
    provider: str
    duration: int
    end_location: Location
    start_location: Location
    vehicle: str
    started_at: AwareDatetime
    ended_at: AwareDatetime
    metadata: Metadata
    # TODO: Shouldn't driver always be present?
    driver: str | None = None
    distance: float | None = None


class ReportRow(TerminalModel):
    vehicle_id: str
    trip_count: int
    total_distance: float | int
    missing_distance_trip_count: int
    latest_ended_at: UtcDatetime | None = None


class Report(TerminalModel):
    start: str
    end: str
    unmatched_vehicle_trip_count: int
    rows: list[ReportRow]


type TWindow = tuple[datetime.datetime | None, datetime.datetime | None]


class ConflictingTripError(Exception):
    pass


class FleetReportService:
    def __init__(self, client: httpx.AsyncClient, base_url: str):
        self.client = client
        self.base_url = base_url

    async def fetch(self, url: str, params: dict | None = None):
        response = await self.client.get(
            url=url,
            params=params,
        )
        response.raise_for_status()
        return response.json()

    async def paginate(self, url: str, params: dict | None = None):
        params = dict(params or {})
        response = await self.fetch(url, params)
        items = list(response["results"])
        seen_cursor = None
        while (cursor := response.get("next")) and cursor != seen_cursor:
            seen_cursor = cursor
            response = await self.fetch(url, {**params, "cursor": cursor})
            items.extend(response["results"])
        return items

    async def fetch_vehicles(self) -> list[Vehicle]:
        rows = await self.paginate(
            url=f"{self.base_url}/vehicles", params={"limit": 10}
        )
        vehicles = [Vehicle.model_validate(row) for row in rows]
        return vehicles

    async def fetch_drivers(self):
        response = await self.fetch(f"{self.base_url}/drivers")
        result = [Driver.model_validate(row) for row in response["results"]]
        return result

    async def fetch_latest_vehicle_locations(self):
        response = await self.fetch(f"{self.base_url}/vehicles/locations")
        result = [
            RealTimeVehicleLatestLocation.model_validate(row)
            for row in response["results"]
        ]
        return result

    async def fetch_historical_vehicle_locations(self, vehicle_id: str):
        response = await self.fetch(f"{self.base_url}/vehicles/{vehicle_id}/locations")
        result = [
            HistoricalVehicleLocation.model_validate(row) for row in response["results"]
        ]
        return result

    def _parse_datetime(self, d: str) -> datetime.datetime:
        dt = datetime.datetime.fromisoformat(d)
        if dt.tzinfo is None:
            raise ValueError("Naive timestamp")
        return dt

    def _format_datetime(self, dt: datetime.datetime) -> str:
        return (
            dt.astimezone(datetime.UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )

    def _validate_window(
        self, start: str | None = None, end: str | None = None
    ) -> TWindow:
        if start is not None:
            start = self._parse_datetime(start)
        if end is not None:
            end = self._parse_datetime(end)
        if start is not None and end is not None and start >= end:
            raise ValueError("start must be < end")
        return start, end

    async def fetch_historical_trips(
        self,
        start: str,
        end: str,
        limit: int = 10,
        vehicle_ids: list[str] | None = None,
    ) -> list[HistoricalTrip]:
        start, end = self._validate_window(start, end)
        assert start is not None
        started_after = start - datetime.timedelta(seconds=1)
        assert end is not None
        started_before = end + datetime.timedelta(seconds=1)

        params = {
            "limit": limit,
        }
        if started_after:
            params["startedAfter"] = self._format_datetime(started_after)
        if started_before:
            params["startedBefore"] = self._format_datetime(started_before)
        if vehicle_ids is not None:
            params["vehicleIds"] = ",".join(vehicle_ids)

        rows = await self.paginate(
            url=f"{self.base_url}/trips",
            params=params,
        )
        trips = [HistoricalTrip.model_validate(row) for row in rows]

        # De-deduplicate
        trips_map = {}
        for trip in trips:
            if trip.id not in trips_map:
                trips_map[trip.id] = trip
                continue
            current_modified_at = trips_map[trip.id].metadata.modified_at
            new_modified_at = trip.metadata.modified_at
            if current_modified_at < new_modified_at:
                trips_map[trip.id] = trip
            elif current_modified_at == new_modified_at and trips_map[trip.id] != trip:
                raise ConflictingTripError

        # Filter
        result = []
        for _, t in trips_map.items():
            if start <= t.started_at < end:
                result.append(t)
        return result

    async def build_report(self, start: str, end: str) -> Report:
        vehicles, trips = await asyncio.gather(
            self.fetch_vehicles(),
            self.fetch_historical_trips(
                start=start,
                end=end,
            ),
        )
        # A vehicle repeated across pages still gets one row.
        vehicle_ids = {vehicle.id for vehicle in vehicles}
        trips_by_vehicle = {}
        unmatched_vehicle_trip_count = 0
        for trip in trips:
            if trip.vehicle not in vehicle_ids:
                unmatched_vehicle_trip_count += 1
                continue
            existing_trip = trips_by_vehicle.get(trip.vehicle, {})
            latest_ended_at = existing_trip.get("latest_ended_at")
            if latest_ended_at is None:
                latest_ended_at = trip.ended_at
            else:
                latest_ended_at = max(latest_ended_at, trip.ended_at)

            trips_by_vehicle[trip.vehicle] = {
                "trip_count": existing_trip.get("trip_count", 0) + 1,
                "total_distance": existing_trip.get("total_distance", 0)
                + (trip.distance or 0),
                "missing_distance_trip_count": existing_trip.get(
                    "missing_distance_trip_count", 0
                )
                + int(trip.distance is None),
                "latest_ended_at": latest_ended_at,
            }
        rows = sorted(
            [
                {
                    "vehicle_id": vehicle_id,
                    "trip_count": trips_by_vehicle.get(vehicle_id, {}).get(
                        "trip_count", 0
                    ),
                    "total_distance": trips_by_vehicle.get(vehicle_id, {}).get(
                        "total_distance", 0
                    ),
                    "missing_distance_trip_count": trips_by_vehicle.get(
                        vehicle_id, {}
                    ).get("missing_distance_trip_count", 0),
                    "latest_ended_at": trips_by_vehicle.get(vehicle_id, {}).get(
                        "latest_ended_at"
                    ),
                }
                for vehicle_id in vehicle_ids
            ],
            key=lambda item: (-item["total_distance"], item["vehicle_id"]),
        )
        report = Report.model_validate(
            {
                "start": start,
                "end": end,
                "unmatched_vehicle_trip_count": unmatched_vehicle_trip_count,
                "rows": rows,
            }
        )
        return report


async def main():
    async with httpx.AsyncClient(
        timeout=10.0,
        headers={
            "Authorization": f"Bearer {os.getenv('API_KEY')}",
            "Connection-Token": os.getenv("CONNECTION_TOKEN"),
        },
    ) as client:
        service = FleetReportService(
            client=client, base_url="https://api.sandbox.withterminal.com/tsp/v1"
        )
        await service.build_report(
            start="2026-11-04T01:51:32.000Z", end="2026-11-06T01:51:32.000Z"
        )


if __name__ == "__main__":
    asyncio.run(main())
