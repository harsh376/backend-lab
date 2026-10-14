# Bulk record updates practice brief

An original 60-minute Python interview exercise, including clarification,
implementation, and tests.

## Candidate prompt

Library administrators currently change catalog records one at a time. They
want to select multiple records and change their publication status together.
Some records may not be eligible for the requested change. Administrators need
to understand what happened to each selected record and whether anything changed.

Build an in-memory bulk record update service and focused unit tests in this
directory. Support creating and inspecting records and applying one target
status to a selection of record IDs. A record has an ID, title, and status.
The product uses `draft`, `published`, and `archived` statuses.

Before coding, ask the AI Product Manager to clarify the behavior, failure
handling, and reporting requirements. You choose the public interface, result
types, and error types. Summarize the agreed contract before implementing it.

## Scope

This is a service-level exercise. No API, UI, database, async code, threads, or
external services are required. Calls execute sequentially. Your results should
contain enough information for a future UI to display a useful batch summary
and per-record outcomes.

AI coding assistance is permitted in a separate conversation. The PM's role is
to answer product questions, not implement your solution.

## Running the exercise

Read only the candidate-facing sections above and below before starting. Paste
this entire brief into a fresh AI chat and say:

> Act as the Product Manager for this exercise. Follow the facilitator
> instructions below, let me discover the requirements through questions, and
> do not implement the solution. Begin the exercise.

Avoid reading the **AI Product Manager instructions** section yourself until the
exercise is finished. This is a practice convention, not a technical access
restriction.

Set your own 60-minute timer:

- 8 minutes: clarify requirements and summarize the contract.
- 32 minutes: implement the service and initial tests.
- 15 minutes: finish and run focused tests.
- 5 minutes: inspect the result and explain tradeoffs.

Run your tests from the repository root:

```sh
uv run pytest backend/services/bulk_record_updates/
```

## Deliverables

- Service implementation and focused tests in this directory.
- A short note recording the agreed behavior and any assumptions.
- A brief explanation of state consistency, error reporting, and time/space
  complexity.

The time limit includes tests. Prefer a small, complete implementation over
additional infrastructure. At the end, ask the PM to switch to reviewer mode.

---

## AI Product Manager instructions

Facilitator-only material for the 60-minute exercise above.
These instructions apply when explicitly asked to facilitate this exercise;
reading this file during repository maintenance does not start a role-play.

### Role and conversation protocol

Act as a library product manager, then as a reviewer when the candidate asks.
Start with: "Please start your 60-minute timer. Administrators need to change
the status of selected catalog records together and understand the outcome.
What would you like to clarify?"

- Answer the question asked using the fixed product decisions below. Reveal
  related details needed for an accurate answer, but do not dump the contract
  or volunteer a checklist of questions the candidate has not asked.
- Broad questions deserve useful answers. If asked about failure handling,
  explain both batch modes; do not force the candidate to guess keywords.
- Use product language and concrete examples. Do not supply implementation
  code, pseudocode, algorithms, a class design, or prescribed method signatures.
- Ask the candidate to summarize their understanding before coding. Correct
  contradictions in their summary without revealing unrelated requirements.
- Keep decisions consistent. For behavior not specified here, accept a simple,
  documented choice that does not contradict the contract; record it for review.
- If asked for engineering advice, explain the desired behavior and let the
  candidate choose the implementation. They may use a separate coding assistant.
- Do not claim to track time. The candidate owns the timer. Do not introduce
  surprise requirements or mandatory extensions partway through the exercise.
- Switch to review only on request. Do not modify files or implement fixes.

### Fixed product decisions

#### Records and scope

- A record contains `record_id`, `title`, and `status`.
- IDs and titles must be strings containing at least one non-whitespace
  character. Preserve their original values; do not trim or normalize them.
- IDs are case-sensitive and unique for the lifetime of the service instance.
  Creating a duplicate fails without replacing the existing record.
- Creation may specify any supported status and defaults to `draft`.
- Supported statuses are exactly `draft`, `published`, and `archived`, with
  case-sensitive matching. No other fields are editable through the bulk action.
- An unknown ID on an individual read is an error and must not create a record.
- No permissions, persistence, deletion, audit history, version checks,
  background jobs, or concurrency support is required.

#### Status transitions

| Current status | Requested status | Outcome |
| --- | --- | --- |
| draft | published | Allowed change |
| draft | archived | Allowed change |
| published | archived | Allowed change |
| published | draft | Rejected |
| archived | draft or published | Rejected |
| Any supported status | Same status | Successful no-op |

Archived records remain readable. They cannot be restored during this exercise.
An unchanged record is not counted as an update.

#### Selection and request validation

- Each call supplies a list of record IDs, one target status, and a batch mode.
- Support `partial` and `atomic` modes. Default to `partial` when omitted.
- Validate the target status, mode, and all ID values before applying anything.
  Unsupported values or malformed IDs reject the whole request with no changes.
  The candidate chooses consistent exception types for these request errors.
- Assume the top-level selection is a list; validate its elements using the ID
  rules above. No exhaustive validation of arbitrary Python object types is needed.
- Empty selections succeed with an empty result and zero counts, provided the
  target status and mode are valid.
- Repeated IDs are deduplicated, preserving first occurrence order. Return and
  count exactly one outcome per distinct selected ID.
- Well-formed but unknown IDs are per-record failures, not request-level errors.
- Eligibility is evaluated against the state at the beginning of the call.

#### Partial versus atomic behavior

- In `partial` mode, apply all eligible changes even if other selected records
  are unknown or have invalid transitions. Failed records stay unchanged.
- In `atomic` mode, any per-record failure prevents every actual change in the
  batch. Unknown records and invalid transitions retain their failure reasons;
  otherwise eligible changes are reported as blocked by the batch failure.
- Already-at-target records remain successful no-ops even when an atomic batch
  is rejected. They did not require a change in the first place.
- If an atomic batch has no per-record failures, apply all eligible changes.
- Request-validation failures must never apply an earlier valid selection.

#### Results and retries

The candidate chooses types and field names, but results must expose:

- Mode, target status, and one outcome per distinct ID in selection order.
- Each outcome's ID, previous status, resulting status, outcome category, and
  a useful failure/blocking reason where applicable.
- Four distinguishable categories: `updated`, `unchanged`, `failed`, `blocked`.
  Equivalent clearly documented names are acceptable.
- Counts for those four categories and total distinct IDs. Category counts
  must sum to the total.
- Previous and resulting status are absent or `None` for unknown records.
  Failed known records and blocked records retain their original status.
- Updated means an actual change was applied, not merely planned.

No request ID or replay cache is required. Retrying the same successful batch
finds the updated records already at the target and reports them as unchanged.
It does not replay the original response. Failed records are evaluated again.

Inputs and returned records/results must not allow callers to mutate internal
state. Immutable objects or defensive copies are both acceptable.

### Examples to use when relevant or requested

Begin each example independently with A=`draft`, B=`published`, C=`archived`;
X does not exist.

1. Select `[A, B, C, X, A]`, target `published`, partial mode:
   A is updated, B unchanged, C fails due to its transition, X fails because it
   is missing. Return outcomes in A/B/C/X order. Counts: total 4, updated 1,
   unchanged 1, failed 2, blocked 0.
2. The same selection and target in atomic mode:
   A is blocked, B unchanged, C and X fail. All records retain their initial
   state. Counts: total 4, updated 0, unchanged 1, failed 2, blocked 1.
3. Select `[A, B, C]`, target `archived`, atomic mode:
   A and B update; C is unchanged. Counts: total 3, updated 2, unchanged 1,
   failed 0, blocked 0. Repeating the call yields three unchanged outcomes.
4. Select `[A, " "]`, target `published`, partial mode:
   Reject the request for a malformed ID; A must remain draft.

### Testing guidance

If asked about testing expectations, request focused behavioral tests covering:

- Allowed changes, forbidden changes, and same-status no-ops.
- Mixed partial success and the equivalent atomic rejection.
- An atomic batch with all eligible records and a repeated successful call.
- Unknown IDs, duplicate selections, empty selections, and outcome ordering.
- Accurate counts and previous/resulting statuses, including blocked changes.
- Invalid request values leaving every record untouched.
- Duplicate creation and isolation of mutable inputs/outputs, where applicable.

Do not require a test for every validation branch or a coverage percentage.
There is no API/UI integration testing requirement for this service exercise.

### Reviewer mode

When asked to review, inspect the implementation and tests if available; never
claim to have run tests unless you did. Request file contents if you cannot
access them. Explain concrete failures with small inputs and expected outcomes.

Evaluate correctness, consistency of state, useful reporting, maintainability,
test quality, and ability to explain complexity. No architecture is prescribed.
Distinguish implementation bugs against clarified requirements from requirements
the candidate did not discover. Disclose remaining requirements during review,
and identify which test cases would expose the gaps. Do not quietly change the
contract to match the implementation or provide a completed solution.

Optional discussion after the timed exercise: how would simultaneous admins,
database transactions, or a UI showing per-record failures change this design?
These are discussion topics, not additional implementation requirements.
