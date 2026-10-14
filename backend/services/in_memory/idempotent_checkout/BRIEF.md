# Idempotent checkout — 60-minute practice exercise

An original Python service-level exercise. Practice clarifying product behavior
with an AI Product Manager, implementing a feature, and testing retries safely.

## Candidate prompt

Our library's checkout clients sometimes retry a request because they did not
receive a response. Today, those retries can create duplicate loans and remove
too many copies from stock. Staff need a reliable way to check out a book to a
patron and safely retry the same request without borrowing another copy.

Build an in-memory checkout service and focused pytest tests in
`backend/services/fifo_reservation_waitlist/idempotent_checkout/`.

Clarify what counts as the same request, what should happen when a request
fails, and what callers should receive on retries. Summarize your acceptance
criteria before implementing. Choose your own interface, result types, and
errors.

This is a self-contained exercise despite its location under the waitlist
directory. Do not modify or integrate the parent waitlist implementation.
Use Python with sequential, in-memory calls. API routes, frontend, databases,
concurrency, payment processing, and external services are out of scope.

## Start the AI PM conversation

Read only the candidate-facing sections above the divider before starting.
The guide below contains the facilitator's answers; save it for review. Give
this entire brief to an AI in a fresh chat and say:

> Facilitate the Idempotent checkout exercise using this brief and its AI PM
> guide. Act as the Product Manager and answer my clarification questions.
> Do not reveal the full contract, suggest questions, or write code unless I
> explicitly ask for implementation help. Ask me to start my 60-minute timer
> and ask my first question. Review my work when I say the exercise is finished.

Attach this file, paste it, or provide its repository path:
`backend/services/fifo_reservation_waitlist/idempotent_checkout/BRIEF.md`.
AI implementation assistance is allowed on request; you own the final code.

## Time budget

- 8 minutes: clarify requirements and summarize acceptance criteria.
- 32 minutes: implement, adding tests as you go.
- 15 minutes: complete and run focused tests.
- 5 minutes: review and explain tradeoffs.

Set your own timer. After writing tests, run them from the repository root:

```sh
uv run pytest backend/services/fifo_reservation_waitlist/idempotent_checkout/
```

## Deliverables

- A working service with observable stock, loan records, and consistent errors.
- Tests for successful checkout, retries, conflicting requests, and failures.
- A short explanation of your state model, invariants, operation complexity,
  and what would need to change for concurrent, persistent production use.

At the hard stop, report what works, what you tested, and what is incomplete.
Prefer complete core behavior over additional features.

---

## AI PM guide — facilitator only

These instructions apply only when the user asks you to facilitate or review
the exercise. Reading or editing this brief does not start a practice session.

### Facilitation instructions

Act as the library Product Manager. Ask the candidate to start their 60-minute
timer and ask their first clarification question. Answer questions using the
fixed decisions below. Give concise, relevant answers; do not recite the full
contract or proactively supply a checklist of questions.

Correct conflicting assumptions when the candidate summarizes their intended
behavior. For unspecified details, accept a reasonable documented choice and
apply it consistently during review. Do not invent surprise requirements or
timed extensions. Do not prescribe data structures, signatures, or algorithms.

If explicitly asked for implementation help, clearly switch from PM to coding
assistant. Do not use that switch to volunteer undiscovered product rules.
Return to the PM role when the candidate resumes requirement questions.

### Scope and operations

- One service instance manages multiple titles, patrons, and checkout requests.
- Support registering a title with initial available stock, adding copies,
  checking out one copy to a patron with an idempotency key, inspecting stock,
  and inspecting loans by ID or as a collection.
- Checkout creates one loan with a unique loan ID, book ID, and patron ID.
  Its successful response contains that loan and the available stock remaining
  immediately after the checkout. The candidate chooses the response shape.
- Titles must be registered explicitly. Duplicate registration and unknown
  titles fail. Patrons do not need registration; any valid patron ID is allowed.
- Registration and restocking are administrative operations without idempotency
  keys. Repeating a restock adds copies again.
- Each checkout borrows exactly one copy. Carts, quantities on checkout,
  reservations, FIFO allocation, returns, due dates, borrowing limits,
  notifications, authentication, and persistence are out of scope.
- A patron can borrow multiple copies of a title through distinct successful
  requests. Do not infer a one-loan-per-patron restriction.

### Validation

- Book IDs, patron IDs, and idempotency keys are nonempty strings. They are
  opaque and case-sensitive; do not trim or normalize them. Whitespace-only
  strings are nonempty and therefore valid for this exercise.
- Initial stock is a nonnegative integer. Restocking requires a positive
  integer. Reject booleans, floats, and numeric strings as stock quantities.
- Unknown loan IDs fail. Reads must not create records.
- No particular error class, message text, or ID format is required. Errors
  must distinguish invalid input, missing records, insufficient stock, and
  idempotency conflicts in a consistent, testable way.
- For multiple ordinary validation errors, any documented precedence is fine.
  The conflict and replay rules below apply to well-formed checkout arguments.

### Successful checkout and state preservation

- For a new request, validate that the title exists and has an available copy.
- Success creates exactly one loan, decrements available stock by one, and
  records the successful request and its response.
- Failure creates no loan, consumes no stock, and stores no successful request
  record. Every operation either succeeds completely or leaves business state
  unchanged. This is sequential business atomicity, not crash recovery.
- Stock must never become negative. For each title, initial stock plus all
  added copies equals current available stock plus the number of its loans.
- Changes to one title must not affect another title's stock or loans.
- Inputs, inspection results, and checkout responses must not expose mutable
  internal state. Immutable results are acceptable.

### Idempotency contract

- Keys have one global namespace for checkout within a service instance, not
  separate namespaces per patron or title. Keep successful request records for
  the lifetime of the instance. Expiration and eviction are out of scope.
- Request identity is the pair `(book_id, patron_id)`. The key itself identifies
  the stored request; no other checkout payload fields are required.
- Same key and identical payload: return the original successful response,
  including the same loan ID and original remaining-stock value. Do not create
  another loan or change stock.
- Same successful key with a different book or patron: raise an idempotency
  conflict and change nothing, even if the new title is unknown or out of stock.
- A successful replay is resolved before current availability is checked.
  Retrying after stock reaches zero must still succeed. Later restocking or
  other checkouts must not change the original replay response.
- A new key means a new checkout, even with the same book and patron. It may
  succeed if stock remains or fail if none remains.
- Failed requests are not remembered. After a failure, the key may be reused
  with the same or a different payload. A request rejected for insufficient
  stock can succeed after restocking.
- Repeated retries must remain safe. Mutating a previously returned object
  must not alter stored state or any future replay response.

### Examples — share only when relevant or requested

**Lost response and replay:** Register book B with two copies. Alice checks out
B with key K1: return loan L1 and remaining stock 1. Bob checks out B with K2:
return loan L2 and remaining stock 0. Alice retries B with K1: return L1 and
remaining stock 1, while stock inspection still reports 0. There are two loans.

**Conflicting reuse:** After K1 succeeds for Alice and B, reuse K1 for Bob and
B, or Alice and another book. Both fail with an idempotency conflict and leave
all state unchanged.

**Retry after failure:** Register C with zero stock. Alice checks out C with
K3 and fails. Add one copy and retry the same request: it succeeds. Alternatively,
before any successful reuse, K3 could be used for a different book or patron.

**New key:** Register D with two copies. Alice checks out D with K4, then D
with K5. Both succeed with distinct loan IDs and stock ends at zero.

### Review at the hard stop

When asked about testing during the exercise, discuss only the relevant
behaviors rather than revealing every unasked requirement. At review, check:

- Successful checkout, exact last-copy checkout, and rejection at zero stock.
- Same-key replay both immediately and after other checkouts or restocking.
- Original response versus current stock inspection.
- Conflicts for changed patron and changed book, across the global key namespace.
- Same payload with a new key creating a distinct loan when stock permits.
- Failed keys remaining reusable, including after restocking and with new data.
- Invalid inputs, missing records, and preservation of all state on failure.
- Independent titles and patrons, unique loans, and the stock invariant.
- Isolation of returned data from internal records and saved replay responses.
- Clear structure, focused public-behavior tests, and an honest complexity
  explanation. No specific algorithm or numerical coverage target is required.

Separate implementation defects, intended rules missed during clarification,
and optional production improvements. Acknowledge undisclosed requirements
rather than claiming the candidate agreed to them. Discuss transactions,
concurrent same-key requests, durable idempotency records, and crash recovery
only as follow-ups; do not require their implementation. Do not write fixes
during review unless asked.
