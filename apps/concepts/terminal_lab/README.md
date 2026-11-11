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

**Reviewed November 11, 2026:** core exercise accepted; all 26 local tests passed.
Pagination, date filtering, deduplication, aggregation, zero-trip vehicles and
sorting are covered. The implementation already fetches vehicles and trips
concurrently; a sequential comparison is deferred to Day 3.

**Deferred polish (not blockers for completion):** print/save the returned report
from the CLI, reject repeated/cyclic pagination cursors, normalize report window
timestamps to UTC, and accept expanded vehicle objects (Day 4). Completion here
records the accepted learning milestone, not that these items have been fixed.

**Build:** fetch all pages of `/vehicles` and `/trips`. For trips request
`startedAfter=S minus one second` and `startedBefore=E plus one second`, then
filter locally with **S <= startedAt < E**. This padded query avoids relying on
server boundary inclusivity. Follow `results` and `next`, sending `cursor=next`
with unchanged filters until no next cursor remains. A short page is not the end.

**Output:** one row per fetched vehicle, including vehicles without trips.
Example shape (illustrative values, not your account's expected totals):

```json
{
  "start": "2026-01-01T00:00:00Z",
  "end": "2026-01-02T00:00:00Z",
  "unmatched_vehicle_trip_count": 0,
  "rows": [
    {"vehicle_id": "A", "trip_count": 2, "total_distance": 10,
     "missing_distance_trip_count": 1,
     "latest_ended_at": "2026-01-01T13:00:00Z"}
  ]
}
```

- Deduplicate by trip ID. For conflicting versions, use greatest
  `metadata.modifiedAt`; conflicting versions with equal timestamps are an error.
- Sum known `distance` values in **kilometers**; count null/missing distances
  separately. Do not round intermediate sums. Trip `duration` is milliseconds.
- Use the maximum qualifying `endedAt`, even if it is after E. Output UTC dates.
- Zero-trip vehicles have counts/total 0 and latest end null. Do not filter them
  out based on status. Count trips for absent vehicles in the unmatched field.
- Sort by total distance descending, then vehicle ID ascending. Use unexpanded
  vehicle IDs for this milestone; expansion is covered on Day 4. Reject malformed
  required IDs/timestamps.

**Accepted checks:** normal cursor chains are consumed; row count equals distinct
vehicle count; row trip counts plus unmatched count equal unique qualifying
trips. Before timing comparisons, save inputs and `local_data/fleet-baseline.json`.

## Day 2 — Dates, duplicates, and missing data

**Build:** test your aggregation without HTTP. Use vehicles A/B/C and window
`[2026-01-01T00:00:00Z, 2026-01-02T00:00:00Z)`. These are minimal aggregation
fixtures, not complete API payloads; add documented required fields if testing
full Pydantic models.

| Trip | Vehicle | Start (UTC) | End (UTC) | Distance km |
| --- | --- | --- | --- | --- |
| t1 | A | Jan 1 00:00 | Jan 1 01:00 | 10 |
| t2 | A | Jan 1 12:00 | Jan 1 13:00 | null |
| t3 | B | Jan 2 00:00 | Jan 2 01:00 | 99 |
| t4 | B | Jan 1 23:30 | Jan 2 00:30 | 7.5 |
| t5 | A | Dec 31 23:59 (2025) | Jan 1 00:30 | 8 |

Add an identical duplicate of t1, expressing its start as
`2026-01-01T05:30:00+05:30`. Use the same modification timestamp.

**Expected output:** envelope contains the input start/end and
`unmatched_vehicle_trip_count: 0`. Rows, in order:

| vehicle_id | trip_count | total_distance | missing_distance_trip_count | latest_ended_at |
| --- | --- | --- | --- | --- |
| A | 2 | 10 | 1 | 2026-01-01T13:00:00Z |
| B | 1 | 7.5 | 0 | 2026-01-02T00:30:00Z |
| C | 0 | 0 | 0 | null |

**Done when:** t1 counts once, t3/t5 are excluded, and t4 counts in full. Adding
an in-window trip for absent vehicle D increases unmatched count without a new
row. A newer version of t1 with distance 11 changes A's total to 11, not its count.
Compare numeric totals with absolute tolerance 1e-6 km.

## Day 3 — Concurrent dataset fetching

**Starting point:** Day 1 already uses `asyncio.gather`. Add a sequential version
for comparison and focus this session on task ownership and failure behavior.

**Build:** fetch `/vehicles` and window-filtered `/trips` concurrently with one
shared HTTP client. Query trips with `startedAfter=S−1 second`,
`startedBefore=E+1 second`; locally enforce S <= startedAt < E. Follow each
endpoint's cursor chain sequentially. Own and await both tasks; close the client
on success or failure.

**Output:** `{start, end, unmatched_vehicle_trip_count, rows}`. Each vehicle row
has `{vehicle_id, trip_count, total_distance, missing_distance_trip_count,
latest_ended_at}`. Deduplicate trips; sum known kilometers; retain zero-trip
vehicles with latest end null; sort by distance descending then ID ascending.

**Done when:** the report matches your sequential result on identical saved
inputs (numeric tolerance 1e-6 km). Log elapsed seconds and request count for
both versions. Demonstrate overlap with locally delayed responses; no fixed live
speedup is required. Failure of either required dataset must prevent a success
report. Optional: compare `gather` and `TaskGroup` after injecting a failure.

## Day 4 — Bounded batches and expansion

**Build:** choose the first up to 60 vehicle IDs in sorted order. Query `/trips`
with `vehicleIds` batches of at most 50, padded S/E start filters, and at most
three active HTTP requests. Paginate every batch; enforce S <= startedAt < E
locally. Repeat with `expand=vehicle,driver`; normalize relation objects to IDs.
Use local fixtures for multiple batches if the account has few vehicles.

**Output:** `{start, end, unmatched_vehicle_trip_count, rows}`, restricted to the
selected vehicles. Rows contain `{vehicle_id, trip_count, total_distance,
missing_distance_trip_count, latest_ended_at}`. Deduplicate trips, sum known
kilometers, retain zero-trip vehicles, sort by distance descending then ID.
Discard trips outside the selection; never count them as unmatched.

**Done when:** expanded/unexpanded inputs give the same report; results match a
sequential query over the same selection and records. Log request count and
`peak_in_flight <= 3`. No batch exceeds 50 IDs. Explain why fewer batched requests
may beat per-vehicle concurrency. Optional: implement the per-vehicle version.

## Day 5 — Retries, deadlines, cancellation

**Build:** make window-filtered `/vehicles` + `/trips` reporting reliable. Start
with configurable 10-second request timeout, 60-second overall deadline, and
three attempts maximum per request. Retry 429, 502, 503, 504 and connection/
timeout failures. Honor `Retry-After`; otherwise use bounded exponential backoff
with jitter. Do not sleep beyond the deadline or hold a request semaphore while
sleeping. Other HTTP failures are nonretryable.

**Success output:** `{start, end, unmatched_vehicle_trip_count, rows}` with rows
`{vehicle_id, trip_count, total_distance, missing_distance_trip_count,
latest_ended_at}`. Include zero-trip vehicles, sum known kilometers, deduplicate,
sort by distance descending then ID. It must match the sequential report over
the same input records.

**Local tests and expected failures:** inject responses with a stub transport and
real-shaped fixtures. Do not overload the live API to trigger failures.

| Injected condition | Expected outcome |
| --- | --- |
| 429 + Retry-After 0.1, then 503, then 200 | Complete report; three attempts, wait honored |
| Three 503 responses | `{"error":"retry_exhausted"}` |
| 400 | One attempt; `{"error":"invalid_request"}` |
| 401/403 | One attempt; `{"error":"authentication_failed"}` |
| Exhausted timeouts or overall deadline | `{"error":"timeout"}` |
| Invalid required response data | `{"error":"invalid_data"}` |
| Cancellation during a request | Await child cleanup, close client, propagate cancellation |

**Done when:** failures exit nonzero with empty stdout and error JSON on stderr;
no partial report is presented as complete. Use a local delayed HTTP server for
socket-timeout testing; in-process transports do not reproduce socket timeouts.

## Day 6 — Backpressure

**Build:** select up to 20 vehicle IDs for a small live run. A producer enqueues
IDs into a queue with capacity 10; three workers fetch `/trips?vehicleIds=...`
for their vehicle, paginate, enforce S <= startedAt < E, and aggregate. Use
padded start filters and share a maximum of three HTTP requests across all tasks.

**Output:** selected-fleet `{start, end, unmatched_vehicle_trip_count, rows}`;
rows are `{vehicle_id, trip_count, total_distance, missing_distance_trip_count,
latest_ended_at}`. Deduplicate, sum known kilometers, retain zero-trip vehicles,
sort by distance descending then ID. Compare with a sequential report on the
same records. Log request count, peak queue size, and peak in-flight requests.

**Done when:** queue peak <= 10, active requests <= 3, no task per input vehicle,
and cancellation while the queue is full does not deadlock. Retaining report
rows and per-vehicle deduplication state is allowed; explain their memory cost.
Replay 200 synthetic vehicle groups locally for scale, giving new records new
IDs. Do not generate live load just to stress the queue. This is a scheduling
drill; a fleet-wide query may be cheaper in practice.

## Day 7 — Driver leaderboard, timed mock

**Build in 45 minutes:** paginate `/drivers` and `/trips` for S/E (padded server
start filters, exact S <= startedAt < E locally). Deduplicate trips; normalize
expanded driver relations. Retain every fetched driver, including zero activity.
Missing driver goes into `unassigned_trip_count`; non-null IDs absent from the
list go into `unmatched_driver_trip_count`.

**Output shape and exact mini-fixture:** list drivers A/B; supply two qualifying
trips assigned to A ending at Jan 1 01:00Z and 13:00Z, and one qualifying trip
without a driver. Use the following window. Expected result:

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

**Done when:** rows sort by count descending, latest end descending (null last),
then ID ascending. Row counts + unassigned + unmatched equal unique qualifying
trips. Changing the unassigned trip to unknown driver D gives unassigned=0,
unmatched=1, unchanged rows. Live totals depend on your account. Spend 15 minutes
reviewing correctness, complexity and failure handling. Use docs/syntax lookup,
not chat assistance, during the mock.

## Optional local server

Start from the repository root:

```sh
.venv/bin/python -m uvicorn apps.concepts.terminal_lab.server:app --host 127.0.0.1 --port 8091
```

Use base URL `http://127.0.0.1:8091/tsp/v1`, API key `mock-key`, connection token
`mock-connection`. It serves `/vehicles`, `/drivers`, `/trips`. Pick one scenario
with `X-Mock-Scenario`: `normal`, `slow` (150ms), `timeout` (2s), `uneven` (short
pages), `flaky` (429, 503, success per query), or `large`. A fresh `X-Mock-Session`
restarts flaky attempts. These headers are local-only.

The mock is a limited legacy fixture: required real-model fields are omitted,
and its duration values are not correctly scaled to milliseconds. Use saved
real-shaped responses for full-model tests. Existing `expected/*.json` files
belong to the old mock schema, not the reports above. No fixed live counts or
mock November dates are required by this guide.

## API references

Reviewed November 10, 2026. Exercise schemas/policies above are our requirements,
not Terminal response formats. External references are for API details:
[models](https://docs.withterminal.com/models/overview),
[Trip](https://docs.withterminal.com/models/trip),
[trip queries](https://docs.withterminal.com/api-reference/trips/list-trips),
[authentication](https://docs.withterminal.com/api-reference/authentication),
[pagination](https://docs.withterminal.com/api-reference/pagination),
[rate limits](https://docs.withterminal.com/api-reference/rate-limits).
