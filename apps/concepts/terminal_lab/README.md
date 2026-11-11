# Terminal API practice — seven days

Spend 60–90 minutes per exercise. Build a Python CLI using `httpx` and `asyncio`;
keep your implementations in `solutions/`. These are practice assignments, not
predictions of Terminal's interview questions.

## Setup once

Configure your shell or IDE environment:

```text
API_KEY=<sandbox secret key>
CONNECTION_TOKEN=<sandbox connection token>
TERMINAL_BASE_URL=https://api.sandbox.withterminal.com/tsp/v1
```

Read these values in your client. Your existing solution currently hardcodes the
base URL; setting the variable alone does not change it. Python does not load
`.env` automatically. Send `Authorization: Bearer <API_KEY>` and
`Connection-Token: <CONNECTION_TOKEN>` on every request. Never print credentials.
If dependencies are missing, run `uv sync --group dev` from the repository root.

Inspect a small page of `/vehicles`, `/drivers`, and `/trips`. Choose a one-day
UTC interval containing an actual trip; call its start **S** and end **E**.
Reuse that interval throughout. Do not assume the account has recent data.
An unavailable endpoint is not an empty dataset.

All endpoint paths below are relative to the base URL. Print report JSON to
stdout and diagnostics to stderr. Store fetched pages and reports in this
folder's Git-ignored `local_data/`. Compare implementations on the same saved
inputs: live data can change between requests. No authenticated calls were made
while preparing this guide.

## Day 1 — Fleet report ✓ Complete

Accepted November 11: 26 local tests passed. Your implementation already uses
concurrent fetching. Remaining polish is deferred: CLI output/save, repeated
cursor errors, UTC window formatting, and expanded vehicle support.

**Task**

Build a report showing each vehicle's activity during a chosen time window.

**Inputs**

- All vehicles from `GET /vehicles`.
- Trips from `GET /trips`.
- Two timezone-aware timestamps: `start` and `end`, with start before end.

Fetch trips with `startedAfter=start minus one second` and
`startedBefore=end plus one second`. Then keep only trips satisfying
`start <= startedAt < end`. A trip may end after the window and still count.
For each endpoint, read `results` and follow `next` using `cursor`, keeping other
parameters unchanged. Stop only when there is no next cursor.

For repeated trip IDs, keep the version with the latest `metadata.modifiedAt`.
If equally recent versions disagree, raise an error. Select the version before
checking whether the trip starts inside the window. Reject invalid required
IDs/timestamps. Use unexpanded vehicle IDs for this exercise.

**Expected output**

A JSON object with `start`, `end`, `unmatched_vehicle_trip_count`, and `rows`.
Each row contains:

- `vehicle_id`: the vehicle's ID.
- `trip_count`: number of unique trips starting inside the window.
- `total_distance`: sum of known distances in kilometers.
- `missing_distance_trip_count`: trips with an omitted or null distance.
- `latest_ended_at`: latest trip end in UTC, or null when there are no trips.

Include vehicles without trips: both counts and distance are 0, latest end is
null. Sort by total distance descending, then vehicle ID ascending.

Count trips whose vehicle is absent from the vehicle list in
`unmatched_vehicle_trip_count`; do not create extra rows for them.

**Done when**

Every page is read, every distinct vehicle has one row, and the sum of row trip
counts plus unmatched count equals the number of unique qualifying trips.
Save the fetched inputs and report in `local_data/` before later comparisons.

## Day 2 — Dates, duplicates, and missing distance

**Task**

Add three independent tests. Start each test from fresh copies of the inputs
below. Reuse `vehicle()`, `trip()`, and `stub_api()` in
`solutions/sequential_fleet_report_test.py`. No live API calls are needed.

**Inputs**

```python
vehicles = [vehicle("A"), vehicle("B"), vehicle("C")]
start = "2026-01-01T00:00:00Z"
end = "2026-01-02T00:00:00Z"
```

Create these trips using `trip()`. All times are UTC; January dates are in 2026.
Use `metadata.modifiedAt = "2026-01-03T00:00:00Z"` for every original trip.

| ID | Vehicle | startedAt | endedAt | distance |
| --- | --- | --- | --- | --- |
| t1 | A | Jan 1 00:00 | Jan 1 01:00 | 10 |
| t2 | A | Jan 1 12:00 | Jan 1 13:00 | omit the key |
| t3 | B | Jan 2 00:00 | Jan 2 01:00 | 99 |
| t4 | B | Jan 1 23:30 | Jan 2 00:30 | 7.5 |
| t5 | A | Dec 31 23:59, 2025 | Jan 1 00:30 | 8 |

Add a copy of t1 with start `2026-01-01T05:30:00+05:30`. Leave its other fields
unchanged. It represents the same trip and instant. C intentionally has no trips.

**Expected output**

Test 1 uses the original inputs. Report `start` and `end` equal the inputs;
`unmatched_vehicle_trip_count` is 0. The rows are:

| vehicle_id | trip_count | total_distance | missing_distance_trip_count | latest_ended_at |
| --- | --- | --- | --- | --- |
| A | 2 | 10 | 1 | 2026-01-01T13:00:00Z |
| B | 1 | 7.5 | 0 | 2026-01-02T00:30:00Z |
| C | 0 | 0 | 0 | null |

Test 2 starts from the original inputs. Add a newer t1 record with:

```text
metadata.modifiedAt = 2026-01-04T00:00:00Z
startedAt           = 2026-01-02T00:00:00Z
endedAt             = 2026-01-02T01:00:00Z
```

It replaces both older copies of t1, then falls outside the window. A now has
only t2: count 1, distance 0, missing-distance count 1, latest end
`2026-01-01T13:00:00Z`. Row order becomes B, A, C. B/C and the envelope are unchanged.

Test 3 starts from the original inputs, **without Test 2's update**. Set
`t2.distance = 0`. A has count 2, distance 10, missing-distance count 0, and
latest end `2026-01-01T13:00:00Z`. Everything else matches Test 1.

**Done when**

All three tests and the existing tests pass. Compare distances with an absolute
tolerance of 1e-6 km. An omitted distance is unknown; a distance of 0 is known.
Null handling is defensive client behavior, not a documented API guarantee.

## Day 3 — Concurrent fetching

**Task**

Compare fetching vehicles and trips one after another with fetching both at
once. Your code already uses `asyncio.gather`; add a sequential comparison.

**Inputs**

- Saved `/vehicles` and `/trips` pages for the same chosen start/end timestamps.
- Replay those pages through a local HTTP stub, adding 150ms delay per request.
- Use one shared HTTP client. Follow each endpoint's next cursors in order.

Run both versions on identical pages. Deduplicate trips by ID using the latest
modification time, then keep `start <= startedAt < end`. Count trips referencing
absent vehicles as unmatched. Do not change the aggregation when changing fetching.

**Expected output**

A JSON object with `start`, `end`, `unmatched_vehicle_trip_count`, and `rows`.
Each row contains:

- `vehicle_id`: the vehicle's ID.
- `trip_count`: number of unique trips starting inside the window.
- `total_distance`: sum of known distances in kilometers.
- `missing_distance_trip_count`: trips with an omitted or null distance.
- `latest_ended_at`: latest trip end in UTC, or null when there are no trips.

Include vehicles without trips: both counts and distance are 0, latest end is
null. Sort by total distance descending, then vehicle ID ascending.

Print elapsed seconds and request count separately to stderr for each run.

**Done when**

Both versions produce the same report (distance tolerance 1e-6 km). Show that
vehicle and trip requests overlap in the concurrent run. In a separate test,
make one endpoint fail while the other is delayed: emit no success report,
finish cancellation/cleanup of outstanding work, and close the client.
No fixed speedup is required on the live API.

## Day 4 — Batches and concurrency limits

**Task**

Fetch trips for a selected set of vehicles, using batches and at most three
active HTTP requests. Handle both ID strings and expanded relationship objects.

**Inputs**

- Select the first up to 60 vehicle IDs after sorting the fetched vehicle list.
- Use a fixed start/end interval containing trips.
- Query `/trips` with `vehicleIds` batches of at most 50 IDs,
  `startedAfter=start minus one second`, and `startedBefore=end plus one second`.
- Read every page in each batch. Locally keep `start <= startedAt < end`.

Run once without expansion and once with `expand=vehicle,driver`. Use an expanded
object's `id` for grouping. Deduplicate trip IDs, keeping the newest modification.
Use replayed fixtures for comparison; if the account has few vehicles, use a
60-vehicle local fixture to exercise two batches.

**Expected output**

A JSON object with `start`, `end`, `unmatched_vehicle_trip_count`, and `rows`.
Each row contains:

- `vehicle_id`: the vehicle's ID.
- `trip_count`: number of unique trips starting inside the window.
- `total_distance`: sum of known distances in kilometers.
- `missing_distance_trip_count`: trips with an omitted or null distance.
- `latest_ended_at`: latest trip end in UTC, or null when there are no trips.

Include vehicles without trips: both counts and distance are 0, latest end is
null. Sort by total distance descending, then vehicle ID ascending.

Only selected vehicles appear. Discard trips outside the selection before
aggregation. The unmatched count is 0 when all selected IDs came from the vehicle
list. Log request count and the largest observed number of active requests.

**Done when**

Both forms of the same records produce identical reports. No request contains
more than 50 vehicle IDs, and no more than three requests are active at once.
Compare against sequential fetching for the same selection and records.

## Day 5 — Retries and cancellation

**Task**

Add retry limits, request timeouts, and an overall deadline to fleet reporting.

**Inputs**

- Saved vehicle/trip responses and fixed start/end timestamps.
- A local stub that returns the response sequences in the table below.
- Maximum three attempts per request, 10-second request timeout, and 60-second
  overall deadline. Make these configurable so tests can use shorter times.

For the successful responses, read all pages, select the newest version of each
trip ID, and include trips with `start <= startedAt < end`. Count references to
absent vehicles as unmatched.

Retry 429, 502, 503, 504 and connection/timeout errors. Honor `Retry-After` when
present; otherwise use bounded exponential backoff with jitter. Waiting and
requests both consume the overall deadline. Release request concurrency slots
before sleeping. Do not retry other HTTP statuses.

**Expected output**

A JSON object with `start`, `end`, `unmatched_vehicle_trip_count`, and `rows`.
Each row contains:

- `vehicle_id`: the vehicle's ID.
- `trip_count`: number of unique trips starting inside the window.
- `total_distance`: sum of known distances in kilometers.
- `missing_distance_trip_count`: trips with an omitted or null distance.
- `latest_ended_at`: latest trip end in UTC, or null when there are no trips.

Include vehicles without trips: both counts and distance are 0, latest end is
null. Sort by total distance descending, then vehicle ID ascending.

Each test below starts with a fresh stub and retry counter. Unaffected endpoints
return valid saved pages. Success prints the complete report; failure prints no
report, exits nonzero, and writes the specified JSON to stderr.

| Stub behavior for one request | Expected result |
| --- | --- |
| 429 with Retry-After 0.1, then 503, then 200 | Success after three attempts; first wait is at least 0.1 seconds |
| 503 on all attempts | `{"error":"retry_exhausted"}` after three attempts |
| 400 | `{"error":"invalid_request"}` after one attempt |
| 401 or 403 | `{"error":"authentication_failed"}` after one attempt |
| Every attempt times out, or overall deadline expires | `{"error":"timeout"}` |
| 200 with invalid required data | `{"error":"invalid_data"}`; no retry |
| Another nonretryable HTTP error | `{"error":"api_error"}` after one attempt |

**Done when**

Every case passes. In another test, cancel a delayed run: child tasks finish
cleanup, the client closes, and cancellation propagates. Do not force failures
by overloading the live API. Use a local delayed HTTP server to test actual
socket timeouts; an in-process transport does not reproduce them.

## Day 6 — Bounded work queue

**Task**

Process vehicles using one producer, a queue of size 10, and three workers.

**Inputs**

- The first up to 20 sorted vehicle IDs for a small live run.
- A fixed start/end interval containing trips.
- For a larger local test: 200 synthetic vehicles, each with one unique trip
  inside the window, distance 1 km, ending at the same timestamp T.

The producer puts IDs in the queue. Each worker requests `/trips` for one
`vehicleIds` value, follows all pages, and updates that vehicle's totals. Use
`startedAfter=start minus one second` and `startedBefore=end plus one second`;
filter with `start <= startedAt < end`. Deduplicate by ID using the newest version.
Share one limit of three active HTTP requests. Do not create a task per vehicle.

**Expected output**

A JSON object with `start`, `end`, `unmatched_vehicle_trip_count`, and `rows`.
Each row contains:

- `vehicle_id`: the vehicle's ID.
- `trip_count`: number of unique trips starting inside the window.
- `total_distance`: sum of known distances in kilometers.
- `missing_distance_trip_count`: trips with an omitted or null distance.
- `latest_ended_at`: latest trip end in UTC, or null when there are no trips.

Include vehicles without trips: both counts and distance are 0, latest end is
null. Sort by total distance descending, then vehicle ID ascending.

Only selected vehicles appear. Log request count, largest queue size, and largest
number of active requests. For the 200-vehicle fixture: 200 rows sorted by ID,
each with count 1, distance 1, missing count 0, latest end T. Unmatched count is 0.

**Done when**

The report matches sequential processing of the same inputs. Queue size never
exceeds 10; active requests never exceed three. In a separate test, cancel while
workers are delayed and the queue is full: every task must exit without hanging.
Keep report rows and deduplication state, but do not accumulate all raw trips.
Explain that this state still consumes memory even with a bounded queue.

## Day 7 — Driver leaderboard

**Task**

Build the driver report in 45 minutes; spend 15 minutes reviewing it. During the
timed attempt, use documentation and syntax lookup, not chat assistance.

**Inputs**

For the live run: all pages of `/drivers` and `/trips`, plus a chosen start/end
interval. Request trips with `startedAfter=start minus one second` and
`startedBefore=end plus one second`; locally keep `start <= startedAt < end`.

For a deterministic test, use drivers A/B, window
`[2026-01-01T00:00:00Z, 2026-01-02T00:00:00Z)`, and these unique trips:

| Trip | Driver | Start (UTC, Jan 1 2026) | End (UTC, Jan 1 2026) |
| --- | --- | --- | --- |
| t1 | A | 00:00 | 01:00 |
| t2 | A | 12:00 | 13:00 |
| t3 | omitted | 14:00 | 15:00 |

Deduplicate trips by ID, retaining the latest modification, before filtering.
Treat expanded driver objects as their IDs. Retain drivers without trips.
Count absent/null driver values as unassigned; count unknown non-null IDs as
unmatched. Reject conflicting versions with identical modification times.

**Expected output**

For the deterministic test:

```json
{
  "start": "2026-01-01T00:00:00Z",
  "end": "2026-01-02T00:00:00Z",
  "unassigned_trip_count": 1,
  "unmatched_driver_trip_count": 0,
  "rows": [
    {"driver_id": "A", "trip_count": 2,
     "latest_ended_at": "2026-01-01T13:00:00Z"},
    {"driver_id": "B", "trip_count": 0, "latest_ended_at": null}
  ]
}
```

Live runs use this schema, but totals depend on the fetched records. Sort by
trip count descending, latest end descending (null last), then driver ID ascending.

**Done when**

The fixture matches. In a separate test starting from the same inputs, set t3's
driver to D without adding D to the driver list: unassigned becomes 0, unmatched
becomes 1, and rows stay unchanged. Row trip counts + unassigned + unmatched
must equal the number of unique qualifying trips.

## Run your tests

```sh
.venv/bin/python -m pytest apps/concepts/terminal_lab/solutions/sequential_fleet_report_test.py
```

Use existing fixture helpers to supply required model fields. Short IDs such as
A/t1 are local test labels, not IDs to send to Terminal. Keep new test inputs
independent; one test's mutations must not affect another.

## Local fixtures and API references

Use `httpx.MockTransport` and saved/synthetic payloads for offline tests. The
legacy `expected/*.json` files belong to an older mock schema, not these reports.

API docs last reviewed November 10, 2026. The report schemas and error policies
above are exercise requirements, not Terminal response formats:
[models](https://docs.withterminal.com/models/overview),
[Trip](https://docs.withterminal.com/models/trip),
[trip queries](https://docs.withterminal.com/api-reference/trips/list-trips),
[authentication](https://docs.withterminal.com/api-reference/authentication),
[pagination](https://docs.withterminal.com/api-reference/pagination),
[rate limits](https://docs.withterminal.com/api-reference/rate-limits).
