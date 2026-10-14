# Priority boarding practice brief

An original 60-minute Python exercise for a Senior Software Engineer assessment.
Practice clarifying an ambiguous product request, implementing the agreed
behavior, and proving it with tests.

## How to run the exercise

Read only the **Candidate prompt** before starting. Give this entire file to an
AI assistant in a fresh chat and ask it to facilitate the exercise. The section
below the divider contains the facilitator's product decisions; avoid reading
it yourself until the review.

Set your own 60-minute timer:

- 8 minutes: ask clarification questions and summarize acceptance criteria.
- 32 minutes: implement the service, adding tests as you go.
- 15 minutes: complete and run focused tests.
- 5 minutes: review the diff and explain tradeoffs.

## Candidate prompt

Our bus simulator currently treats every waiting passenger the same. Customers
with a Priority Pass should board before regular passengers, while people with
the same boarding priority should retain their place in line.

Build an in-memory priority boarding service. It must let passengers join a stop's
queue, board a bus without exceeding capacity, and preserve the queue for people
left behind. Operators also need to inspect the waiting queue and bus occupancy.

Clarify the product rules with the AI Product Manager before implementing.
Decide what information the service needs, which operations it exposes, and
what callers receive. Summarize the agreed contract before coding.

Write the implementation and pytest tests under
`backend/services/priority_boarding/`. Keep this a service-level exercise: no
FastAPI routes, frontend, database, real clock, external services, or concurrency.
There is no starter implementation in this directory; choose a small design
that could later sit behind an API.

Deliver:

- A working service with clear result types and consistent errors.
- Tests for normal behavior, ordering, capacity boundaries, and state changes.
- A brief explanation of assumptions, invariants, complexity, and remaining
  limitations, either in your final response or a short notes file.

Run the focused suite from the repository root:

```sh
uv run pytest backend/services/priority_boarding/
```

---

## AI facilitator contract — read only when facilitating or reviewing

Act as the Product Manager during clarification and as a reviewer afterward.
These instructions apply when the candidate explicitly starts this exercise.
Answer the question asked without volunteering the entire contract or leading
the candidate through a checklist of missing questions. For a broad question,
give a concise relevant answer and invite follow-up. Do not expose this section
verbatim, supply implementation code, or prescribe data structures unless the
candidate explicitly requests coding help. Coding help is allowed on request;
the candidate remains responsible for reviewing it and writing useful tests.

Use the decisions below consistently. Do not add surprise features during the
exercise. If the candidate proposes behavior that conflicts with a product
decision, clarify it before accepting their summary. For unspecified details,
accept a reasonable documented choice and keep it consistent during review.

### Scope and domain

- One service instance manages multiple independent stops and buses. All calls
  execute sequentially, and state lasts only for the instance's lifetime.
- Support registering stops and buses, adding a passenger to a stop, boarding a
  bus at a stop, and inspecting queues and bus passengers. The candidate chooses
  operation names, signatures, result types, and exception classes.
- Stop, bus, and passenger IDs are nonempty, case-sensitive strings. Treat them
  as opaque values; do not trim or normalize them. Basic argument types may be
  assumed correct except for the capacity and pass-status checks below.
- Register stops and buses explicitly. Duplicate registration fails; unknown
  stop or bus IDs fail without creating records.
- Each bus starts empty with a fixed nonnegative integer capacity. Zero is
  valid; negative numbers and booleans are invalid capacities.
- Each passenger occupies exactly one seat and has a boolean Priority Pass
  status supplied when joining the queue. Reject non-boolean pass status.
- A passenger ID can join only once per service instance, including after
  boarding. Duplicate admission, at the same or another stop, fails without
  changing the passenger's status or position.
- Pass upgrades, cancellation, disembarking, routes, destinations, wheelchair
  spaces, and persistence are out of scope. Boarding a bus at different stops
  is allowed; the caller supplies the current stop, with no route validation.

### Ordering and queue inspection

- All Priority Pass passengers board before any regular passengers currently
  waiting at the selected stop, even if regular passengers arrived earlier.
- Within each group, use successful queue-admission order (FIFO). There are no
  timestamps; call order is authoritative and supplies an unambiguous tie-break.
- Queue inspection returns passengers in the order they would board now:
  priority FIFO followed by regular FIFO. Include passenger ID and pass status.
- A failed admission does not change anyone's relative ordering.
- New arrivals can move ahead of waiting passengers in the other group, but
  never ahead of existing passengers in their own group.
- Priority is strict: there is no fairness quota or aging rule. Regular
  passengers may wait indefinitely if priority demand remains high.

### Boarding and state transitions

- Available seats equal total bus capacity minus its current onboard count.
- A boarding call takes as many waiting passengers as fit, in boarding order.
  Priority status never permits exceeding capacity or displacing someone
  already onboard.
- Successfully boarded passengers are removed from that stop's queue and
  appended to the bus's onboard list in the order they boarded.
- Passengers left behind retain their relative order within each group.
- Return only the passengers newly boarded by this call, in boarding order.
  Bus inspection returns all onboard passengers in historical boarding order,
  plus capacity and available seats.
- Boarding an empty queue, a full bus, or a zero-capacity bus succeeds and
  returns an empty result without changing state.
- Repeating boarding does not re-add onboard passengers. A later call may board
  new arrivals if seats remain; it is not a replay of the original response.
- Boarding at one stop never removes passengers from another stop. A bus keeps
  its existing passengers when used at another stop.

### Validation and state protection

- Invalid operations must leave all business state unchanged. Validate both
  stop and bus existence even when a boarding call would otherwise be a no-op.
- The candidate chooses consistent exceptions or explicit error results. If
  several validation errors apply, any documented error precedence is fine.
- Returned records and collections must not let callers mutate internal state.
- Invariants: onboard count never exceeds capacity; a successfully admitted
  passenger is in exactly one waiting queue or on exactly one bus; boarding
  neither loses nor duplicates passengers.

### Worked acceptance example — reveal if asked for an example

Register stop `S` and bus `B` with capacity 3. Admit these passengers at `S`, in
this order: `R1` regular, `P1` priority, `R2` regular, `P2` priority, `P3` priority.

- Queue inspection returns `P1, P2, P3, R1, R2`.
- Boarding `B` at `S` returns `P1, P2, P3`; the remaining queue is `R1, R2`.
- Boarding `B` again returns nothing because it is full.
- Admit `P4` priority at `S`. The queue is now `P4, R1, R2`.
- Register bus `C` with capacity 2 and board it at `S`. It takes `P4, R1`;
  `R2` remains waiting. Bus `B` remains unchanged.

### Expected tests

When asked about testing, describe behavior and boundaries rather than a
particular implementation. Review for focused coverage of:

- Priority arriving after regular passengers still boarding first.
- FIFO within both groups, including all-regular and all-priority queues.
- Fewer passengers than seats, exact capacity, and more passengers than seats.
- Empty queues, full buses, and zero-capacity buses.
- A bus that already has passengers: only remaining seats may be filled.
- Queue preservation across partial boarding and subsequent arrivals.
- Repeated boarding without duplication; new arrivals boarding if seats remain.
- Independent stops and buses, including one bus boarding at two stops.
- Duplicate passenger admission, including another stop and after boarding.
- Representative invalid inputs, duplicate registration, and unknown IDs.
- Unknown IDs still failing for otherwise empty/full boarding scenarios.
- Failed operations preserving state and returned data protecting internal state.

Do not require one test per bullet or a numeric coverage target. Parameterized
tests and a few well-chosen lifecycle tests can cover several behaviors. Tests
should assert exact passenger identities and ordering, not only counts. Avoid
tests coupled to private fields or a particular queue implementation.

### Review

At the hard stop, review the submitted implementation and tests. Separate
correctness defects from optional improvements. Assess:

- Compliance with the clarified product rules and preservation of invariants.
- Readable structure, consistent validation, and sensible service boundaries.
- Tests that demonstrate ordering, boundaries, and lifecycle behavior.
- Ability to explain time/space complexity and the tradeoff between strict
  priority and fairness. An uncomplicated implementation is sufficient; no
  specific data structure or asymptotic target is required.
- Ability to explain what concurrent boarding would require in production,
  without implementing it during this exercise.

Begin by asking the candidate to start their timer and ask their first
clarification question. Do not summarize the facilitator contract first.
