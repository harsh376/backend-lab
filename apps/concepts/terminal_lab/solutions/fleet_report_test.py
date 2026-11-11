import datetime

import httpx
import pydantic
import pytest

from apps.concepts.terminal_lab.solutions.fleet_report import (
    ConflictingTripError,
    FleetReportService,
)

BASE_URL = "https://api.test/tsp/v1"
START = "2026-01-01T00:00:00Z"
END = "2026-01-02T00:00:00Z"


def vehicle(vehicle_id: str, status: str = "active") -> dict:
    return {
        "id": vehicle_id,
        "vin": f"VIN-{vehicle_id}",
        "provider": "geotab",
        "status": status,
        "groups": [],
        "devices": [],
        "metadata": {"modifiedAt": "2025-12-01T00:00:00Z"},
    }


def trip(
    trip_id: str,
    vehicle_id: str,
    started_at: str = "2026-01-01T06:00:00Z",
    ended_at: str = "2026-01-01T07:00:00Z",
    distance: float | None = 10,
    modified_at: str = "2026-01-03T00:00:00Z",
) -> dict:
    duration = datetime.datetime.fromisoformat(
        ended_at
    ) - datetime.datetime.fromisoformat(started_at)
    return {
        "id": trip_id,
        "sourceId": f"src-{trip_id}",
        "provider": "geotab",
        "duration": int(duration.total_seconds() * 1000),
        "startLocation": {"latitude": 0.0, "longitude": 0.0},
        "endLocation": {"latitude": 1.0, "longitude": 1.0},
        "vehicle": vehicle_id,
        "distance": distance,
        "startedAt": started_at,
        "endedAt": ended_at,
        "metadata": {"modifiedAt": modified_at},
    }


def stub_api(
    vehicles: list[dict],
    trips: list[dict],
    page_size: int = 100,
    requests: list[tuple[str, dict]] | None = None,
) -> httpx.MockTransport:
    """Serve the lists in pages, using offsets as cursors; record into `requests`."""
    results = {"/vehicles": vehicles, "/trips": trips}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/tsp/v1")
        params = dict(request.url.params)
        if requests is not None:
            requests.append((path, params))
        offset = int(params.get("cursor", 0))
        body = {"results": results[path][offset : offset + page_size]}
        if offset + page_size < len(results[path]):
            body["next"] = str(offset + page_size)
        return httpx.Response(200, json=body)

    return httpx.MockTransport(handler)


# Fetching


async def test_trips_query_pads_window_by_one_second():
    requests = []
    transport = stub_api([vehicle("A")], [trip("t1", "A")], requests=requests)
    async with httpx.AsyncClient(transport=transport) as client:
        await FleetReportService(client, BASE_URL).build_report(START, END)

    params = requests[-1][1]
    assert params["startedAfter"] == "2025-12-31T23:59:59.000Z"
    assert params["startedBefore"] == "2026-01-02T00:00:01.000Z"
    assert "endedBefore" not in params


async def test_all_vehicle_pages_are_fetched():
    requests = []
    vehicles = [vehicle(v) for v in "ABCDE"]
    transport = stub_api(vehicles, [], page_size=2, requests=requests)
    async with httpx.AsyncClient(transport=transport) as client:
        report = await FleetReportService(client, BASE_URL).build_report(START, END)

    assert [path for path, _ in requests].count("/vehicles") == 3
    assert [r.vehicle_id for r in report.rows] == ["A", "B", "C", "D", "E"]


async def test_all_trip_pages_are_fetched_with_unchanged_filters():
    requests = []
    trips = [trip(f"t{i}", "A") for i in range(5)]
    transport = stub_api([vehicle("A")], trips, page_size=2, requests=requests)
    async with httpx.AsyncClient(transport=transport) as client:
        report = await FleetReportService(client, BASE_URL).build_report(START, END)

    first, *rest = [params for path, params in requests if path == "/trips"]
    assert len(rest) == 2
    for params in rest:
        assert params.pop("cursor")
        assert params == first
    assert report.rows[0].trip_count == 5


async def test_short_page_is_not_the_end():
    # The server returns 1 row per page although the client asks for more.
    requests = []
    trips = [trip(f"t{i}", "A") for i in range(3)]
    transport = stub_api([vehicle("A")], trips, page_size=1, requests=requests)
    async with httpx.AsyncClient(transport=transport) as client:
        report = await FleetReportService(client, BASE_URL).build_report(START, END)

    assert [path for path, _ in requests].count("/trips") == 3
    assert report.rows[0].trip_count == 3


# Window


async def test_start_is_inclusive_and_end_is_exclusive():
    trips = [
        trip("at-start", "A", "2026-01-01T00:00:00Z", "2026-01-01T01:00:00Z"),
        trip("before-start", "A", "2025-12-31T23:59:59Z", "2026-01-01T01:00:00Z"),
        trip("at-end", "A", "2026-01-02T00:00:00Z", "2026-01-02T01:00:00Z"),
        trip("before-end", "A", "2026-01-01T23:59:59Z", "2026-01-02T00:30:00Z"),
    ]
    async with httpx.AsyncClient(transport=stub_api([vehicle("A")], trips)) as client:
        report = await FleetReportService(client, BASE_URL).build_report(START, END)

    assert report.rows[0].trip_count == 2


async def test_window_compares_instants_across_offsets():
    # 05:29 +05:30 is 23:59 UTC the previous day.
    trips = [
        trip("inside", "A", "2026-01-01T05:30:00+05:30", "2026-01-01T06:30:00+05:30"),
        trip("outside", "A", "2026-01-01T05:29:00+05:30", "2026-01-01T06:30:00+05:30"),
    ]
    async with httpx.AsyncClient(transport=stub_api([vehicle("A")], trips)) as client:
        report = await FleetReportService(client, BASE_URL).build_report(START, END)

    assert report.rows[0].trip_count == 1


async def test_envelope_echoes_window():
    async with httpx.AsyncClient(transport=stub_api([vehicle("A")], [])) as client:
        report = await FleetReportService(client, BASE_URL).build_report(START, END)

    assert report.start == START
    assert report.end == END


async def test_rejects_window_with_start_not_before_end():
    async with httpx.AsyncClient(transport=stub_api([vehicle("A")], [])) as client:
        with pytest.raises(ValueError):
            await FleetReportService(client, BASE_URL).build_report(END, START)


# Deduplication


async def test_identical_duplicate_counts_once():
    trips = [trip("t1", "A"), trip("t1", "A")]
    async with httpx.AsyncClient(transport=stub_api([vehicle("A")], trips)) as client:
        report = await FleetReportService(client, BASE_URL).build_report(START, END)

    assert report.rows[0].trip_count == 1
    assert report.rows[0].total_distance == pytest.approx(10, abs=1e-6)


@pytest.mark.parametrize("newer_first", [True, False])
async def test_greatest_modified_at_wins(newer_first):
    older = trip("t1", "A", distance=10, modified_at="2026-01-03T00:00:00Z")
    newer = trip("t1", "A", distance=11, modified_at="2026-01-04T00:00:00Z")
    trips = [newer, older] if newer_first else [older, newer]
    async with httpx.AsyncClient(transport=stub_api([vehicle("A")], trips)) as client:
        report = await FleetReportService(client, BASE_URL).build_report(START, END)

    assert report.rows[0].trip_count == 1
    assert report.rows[0].total_distance == pytest.approx(11, abs=1e-6)


async def test_conflicting_versions_with_equal_modified_at_raise():
    trips = [trip("t1", "A", distance=10), trip("t1", "A", distance=12)]
    async with httpx.AsyncClient(transport=stub_api([vehicle("A")], trips)) as client:
        with pytest.raises(ConflictingTripError):
            await FleetReportService(client, BASE_URL).build_report(START, END)


# Aggregation


async def test_distance_sums_known_values_without_rounding():
    trips = [trip("t1", "A", distance=0.1), trip("t2", "A", distance=0.2)]
    async with httpx.AsyncClient(transport=stub_api([vehicle("A")], trips)) as client:
        report = await FleetReportService(client, BASE_URL).build_report(START, END)

    assert report.rows[0].total_distance == pytest.approx(0.3, abs=1e-6)
    assert report.rows[0].missing_distance_trip_count == 0


async def test_null_and_missing_distances_are_counted_separately():
    missing = {k: v for k, v in trip("t3", "A").items() if k != "distance"}
    trips = [trip("t1", "A", distance=10), trip("t2", "A", distance=None), missing]
    async with httpx.AsyncClient(transport=stub_api([vehicle("A")], trips)) as client:
        report = await FleetReportService(client, BASE_URL).build_report(START, END)

    row = report.rows[0]
    assert row.trip_count == 3
    assert row.total_distance == pytest.approx(10, abs=1e-6)
    assert row.missing_distance_trip_count == 2


async def test_latest_ended_at_is_max_qualifying_end_even_after_window():
    trips = [
        trip("t1", "A", "2026-01-01T23:00:00Z", "2026-01-02T03:00:00Z"),
        trip("t2", "A", "2026-01-01T01:00:00Z", "2026-01-01T02:00:00Z"),
        # Ends later but starts outside the window.
        trip("t3", "A", "2026-01-02T00:00:00Z", "2026-01-02T05:00:00Z"),
    ]
    async with httpx.AsyncClient(transport=stub_api([vehicle("A")], trips)) as client:
        report = await FleetReportService(client, BASE_URL).build_report(START, END)

    assert report.rows[0].latest_ended_at == datetime.datetime(
        2026, 1, 2, 3, tzinfo=datetime.UTC
    )


async def test_latest_ended_at_is_output_in_utc():
    trips = [trip("t1", "A", "2026-01-01T05:30:00+05:30", "2026-01-01T06:30:00+05:30")]
    async with httpx.AsyncClient(transport=stub_api([vehicle("A")], trips)) as client:
        report = await FleetReportService(client, BASE_URL).build_report(START, END)

    output = report.model_dump(mode="json")
    assert output["rows"][0]["latest_ended_at"] == "2026-01-01T01:00:00Z"


# Rows


async def test_zero_trip_vehicles_are_present():
    vehicles = [vehicle("A"), vehicle("B")]
    trips = [trip("t1", "A")]
    async with httpx.AsyncClient(transport=stub_api(vehicles, trips)) as client:
        report = await FleetReportService(client, BASE_URL).build_report(START, END)

    assert report.model_dump(mode="json")["rows"][1] == {
        "vehicle_id": "B",
        "trip_count": 0,
        "total_distance": 0,
        "missing_distance_trip_count": 0,
        "latest_ended_at": None,
    }


async def test_vehicles_are_not_filtered_by_status():
    vehicles = [vehicle("A"), vehicle("B", status="inactive")]
    async with httpx.AsyncClient(transport=stub_api(vehicles, [])) as client:
        report = await FleetReportService(client, BASE_URL).build_report(START, END)

    assert [r.vehicle_id for r in report.rows] == ["A", "B"]


async def test_one_row_per_distinct_vehicle():
    vehicles = [vehicle("A"), vehicle("A"), vehicle("B")]
    async with httpx.AsyncClient(transport=stub_api(vehicles, [])) as client:
        report = await FleetReportService(client, BASE_URL).build_report(START, END)

    assert [r.vehicle_id for r in report.rows] == ["A", "B"]


async def test_trips_for_absent_vehicles_are_unmatched():
    trips = [trip("t1", "A"), trip("t2", "D"), trip("t3", "D")]
    async with httpx.AsyncClient(transport=stub_api([vehicle("A")], trips)) as client:
        report = await FleetReportService(client, BASE_URL).build_report(START, END)

    assert report.unmatched_vehicle_trip_count == 2
    assert [r.vehicle_id for r in report.rows] == ["A"]
    counted = sum(r.trip_count for r in report.rows)
    assert counted + report.unmatched_vehicle_trip_count == 3


async def test_sort_by_distance_desc_then_vehicle_id_asc():
    vehicles = [vehicle(v) for v in ("b", "c", "a", "d")]
    trips = [
        trip("t1", "a", distance=5),
        trip("t2", "b", distance=5),
        trip("t3", "c", distance=20),
    ]
    async with httpx.AsyncClient(transport=stub_api(vehicles, trips)) as client:
        report = await FleetReportService(client, BASE_URL).build_report(START, END)

    assert [r.vehicle_id for r in report.rows] == ["c", "a", "b", "d"]


# Validation


@pytest.mark.parametrize(
    "field, value",
    [
        ("startedAt", "2026-01-01T06:00:00"),
        ("endedAt", "not-a-timestamp"),
        ("id", None),
        ("vehicle", None),
    ],
)
async def test_rejects_malformed_trip(field, value):
    trips = [{**trip("t1", "A"), field: value}]
    async with httpx.AsyncClient(transport=stub_api([vehicle("A")], trips)) as client:
        with pytest.raises(pydantic.ValidationError):
            await FleetReportService(client, BASE_URL).build_report(START, END)


async def test_rejects_vehicle_without_id():
    vehicles = [{k: v for k, v in vehicle("A").items() if k != "id"}]
    async with httpx.AsyncClient(transport=stub_api(vehicles, [])) as client:
        with pytest.raises(pydantic.ValidationError):
            await FleetReportService(client, BASE_URL).build_report(START, END)
