# FIFO reservation waitlist — 60-minute practice exercise

An original Python service-level exercise. Practice gathering requirements from
an AI Product Manager, implementing a small feature, and verifying its behavior.

## Candidate prompt

Our library needs a fair way to manage demand for popular books. Patrons should
be able to join a book's waitlist and cancel their request. When copies become
available, the earliest waiting patrons should get first access. Staff need to
see who is waiting, who has a copy reserved, and how many copies remain available.

Build an in-memory reservation waitlist service and focused pytest tests in
`apps/api/services/fifo_reservation_waitlist/`.

Clarify the product rules with the AI PM before coding. In particular, turn
"first access" and "become available" into behavior you can demonstrate. Choose
your own service interface, result types, and errors, and summarize the agreed
acceptance criteria before implementation.

Keep this exercise at the service level: no API routes, frontend, database,
external notifications, real clock, background jobs, or concurrency. All calls
execute sequentially. There is no starter implementation to repair.

## Start the AI PM conversation

Read only the candidate-facing sections above the divider before starting.
The AI PM guide below the divider contains the facilitator's answers; avoid
reading it until review. Give this entire brief to an AI in a fresh chat and say:

> Facilitate the FIFO reservation waitlist exercise using this brief, including
> its AI PM guide. Act as the Product Manager and answer my clarification
> questions. Do not reveal the whole contract, suggest questions, or write code
> unless I explicitly ask for implementation help. Start by asking me to start
> my 60-minute timer and ask my first question. Review my implementation when
> I say the exercise is finished.

Attach or paste this single file, or give an assistant with repository access
its path: `apps/api/services/fifo_reservation_waitlist/BRIEF.md`.
AI implementation assistance is allowed on request; you own the final code.

## Time budget

- 8 minutes: clarify requirements and summarize acceptance criteria.
- 32 minutes: implement, adding tests as you go.
- 15 minutes: finish and run focused tests.
- 5 minutes: review and explain tradeoffs.

Set your own timer. Run tests from the repository root after writing them:

```sh
uv run pytest apps/api/services/fifo_reservation_waitlist/
```

## Deliverables

- A working service with clear observable results and consistent errors.
- Tests demonstrating ordering, multiple copies, cancellation, repeated
  operations, and representative failure cases.
- A short explanation of your state model, invariants, operation complexity,
  and what would need to change for concurrent production requests.

Prefer a complete, straightforward implementation over extra features. At the
hard stop, report what works, what you tested, and what remains incomplete.

---

## AI PM guide — facilitator only

These instructions apply when the user asks you to facilitate or review this
exercise. Reading this file while editing the brief does not start a session.

### Facilitation

Act as the library Product Manager. Begin by asking the candidate to start their
60-minute timer and ask their first clarification question. Answer only what
they ask, using the fixed product decisions below. For broad questions, give a
concise relevant answer rather than reciting every rule. Do not proactively
provide a checklist of questions, the full contract, or a solution.

Correct conflicting assumptions when the candidate summarizes requirements.
For unspecified details, accept a reasonable documented choice and use it
consistently in review. Do not add surprise requirements or timed extensions.
Do not prescribe data structures or method signatures. If explicitly asked for
coding help, provide it, clearly switching from PM to coding assistant; do not
use that switch to volunteer undiscovered product rules.

### Scope and operations

- A service instance manages multiple independent book titles. Copies of a
  title are interchangeable; individual copy IDs and patron registration are
  out of scope.
- Support registering a title with initial available stock, adding available
  copies, joining a waitlist, canceling a reservation, explicitly allocating
  available copies for one title, collecting a reserved copy, and inspecting
  reservations, waiting order, and stock.
- The candidate chooses operation names, signatures, result types, and errors.
- State is in memory and calls are sequential. Expiration, priorities, loans,
  due dates, delivery notifications, authentication, and persistence are out
  of scope. Do not require an HTTP API or UI.
- Adding stock represents newly acquired or returned copies; the caller is
  responsible for reporting physical returns correctly. No loan tracking is
  required.

### Admission and FIFO

- Explicitly register each title once. Unknown titles and duplicate title
  registration fail without changing state.
- Book and patron IDs are nonempty, case-sensitive strings, treated as opaque
  values without trimming. Basic argument types may otherwise be assumed valid,
  except for stock quantities as specified below.
- Every successful join creates a unique reservation ID and a `WAITING` record.
  Keep records for the lifetime of the instance, including terminal records.
- A patron may have at most one active reservation per title. Both `WAITING`
  and `RESERVED` are active. A duplicate join fails; it does not replace a
  record, change queue position, or return a successful new reservation.
- The same patron may wait for different titles. After cancellation or
  collection, they may rejoin the same title with a new ID at the tail.
- FIFO is successful join-call order for that title. There are no timestamps
  or ties to resolve. Failed joins never alter relative order.
- Waiting inspection returns only `WAITING` records in FIFO order. Inspection
  also supports finding current reserved records and looking up a reservation
  by ID. Reserved-list ordering is the candidate's documented choice.

### Stock and allocation

- Initial stock is a nonnegative integer; adding stock requires a positive
  integer. Reject booleans, floats, and negative values; reject zero for adds.
- Stock inspection exposes available and reserved counts for a title. Available
  excludes copies held by `RESERVED` reservations.
- Allocation is explicit. Registering stock, adding stock, joining, and
  cancellation do not automatically allocate copies.
- An allocation call reserves one copy for each of the first N waiting records,
  where N is the smaller of available stock and the number waiting. Allocate
  as many as fit, not just one.
- Each selected record changes from `WAITING` to `RESERVED`. Available decreases
  by N and reserved increases by N. Waiting patrons cannot skip ahead, even
  if they ask to collect directly.
- Return only the records newly reserved by that call, in FIFO order. Empty
  queues and zero available copies yield an empty successful result.
- Repeating allocation does not reserve another copy for an already reserved
  patron. Later calls can allocate newly available copies or serve new arrivals.
  There is no request-ID replay mechanism.
- Unknown titles fail even when allocation would otherwise be a no-op.

### Cancellation and collection

- Canceling `WAITING` changes it to `CANCELED`, removing it from the queue.
  Other waiting records keep their relative positions.
- Canceling `RESERVED` changes it to `CANCELED` and releases its one held copy:
  reserved decreases by one and available increases by one. The next waiting
  patron receives it only on the next explicit allocation call.
- Repeated cancellation of `CANCELED` succeeds without further changes.
- Collecting `RESERVED` changes it to `COLLECTED` and decreases reserved by one.
  Available is unchanged: the copy leaves the library rather than becoming free.
- Repeated collection of `COLLECTED` succeeds without further changes.
- Collecting `WAITING` or `CANCELED`, and canceling `COLLECTED`, fail.
- Unknown reservation IDs fail. Terminal records remain queryable. No operation
  moves a terminal record back to an active status.

### State protection and invariants

- Failed operations leave business state unchanged. Any consistent error
  precedence is acceptable when multiple inputs are invalid.
- Returned records and collections must not expose mutable internal state.
- Available and reserved counts are never negative. Reserved count equals the
  number of `RESERVED` records for that title.
- Each reservation holds at most one copy. Allocating or canceling must neither
  create nor lose copies. For each title, initial plus added copies equals
  available plus reserved plus the number of `COLLECTED` records.
- Operations on one title must not affect another title's queue or stock.

### Example — share only if asked

Register title `B` with zero copies. Alice, Bob, and Cara join in that order.

1. Add two copies. Everyone is still waiting until allocation is called.
2. Allocate `B`: return Alice and Bob as reserved; Cara remains waiting.
   Stock is available 0, reserved 2.
3. Allocate again: return an empty result and leave stock unchanged.
4. Cancel Alice: stock is available 1, reserved 1. Cara still waits.
5. Alice rejoins with a new reservation ID, behind Cara.
6. Allocate: Cara gets the released copy; Alice remains waiting.
7. Bob collects: stock is available 0, reserved 1. Repeating Bob's collection
   changes nothing. Cara holds the one remaining copy.

### Tests and review

When asked about testing, discuss the relevant behaviors rather than exposing
every unasked requirement. At the end, assess:

- Exact FIFO identities across partial allocation, cancellation, and rejoining.
- Zero, fewer, equal, and more available copies than waiting patrons.
- Multiple titles and a patron with reservations on different titles.
- Duplicate active joins, including after allocation.
- Cancellation before and after allocation, release, and repeated cancellation.
- Collection and repeated collection; invalid lifecycle transitions.
- Explicit allocation and repeat calls without duplicate holds.
- Representative invalid IDs and quantities, preserved state after failure,
  and input/output state isolation.
- Readability, consistency, complexity explanation, and focused public-behavior
  tests. No particular algorithm, numeric coverage target, or one-test-per-rule
  requirement applies.

Separate implemented correctness defects, product rules missed during
clarification, and optional production improvements. The guide is the intended
contract, but acknowledge when a rule was never discussed rather than claiming
it was agreed. Discuss concurrent allocation and database transactions only as
a follow-up; their implementation is out of scope. Do not write fixes during
review unless asked.
