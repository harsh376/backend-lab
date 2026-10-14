# Inventory service: atomicity and idempotency

An original Python practice exercise. Suggested time: 60–75 minutes, including
your own tests. Implement the service and tests in this directory.

## Scenario

A checkout system reserves inventory before payment. Requests can be retried
because callers do not always receive the response. A cart may contain multiple
products: either the entire cart is reserved or nothing is reserved.

Build an in-memory `InventoryService`. No API, UI, database, external services,
threads, or async code are required. Assume calls execute sequentially. Here,
atomicity means all-or-nothing business operations, not crash recovery.

## Stage 1: stock and reservation lifecycle

Provide these operations; choose your own result types and exception classes:

```python
receive_stock(product_id: str, quantity: int) -> StockSnapshot
get_stock(product_id: str) -> StockSnapshot
reserve(items: dict[str, int], request_id: str) -> ReservationSnapshot
commit(reservation_id: str, request_id: str) -> ReservationSnapshot
release(reservation_id: str, request_id: str) -> ReservationSnapshot
get_reservation(reservation_id: str) -> ReservationSnapshot
```

`receive_stock` creates an unknown product or adds units to an existing one.
It is an administrative operation and is **not idempotent**: calling it twice
receives stock twice. The other three mutation operations use request IDs.

A stock snapshot exposes `product_id`, `on_hand`, `reserved`, and `available`.
A reservation snapshot exposes a unique `reservation_id`, its product/quantity
mapping, and a status: `ACTIVE`, `COMMITTED`, or `RELEASED`.

Rules:

- Product IDs and request IDs must be nonempty strings. Treat them as opaque,
  case-sensitive values; do not trim or otherwise normalize them.
- Quantities must be positive integers. Reject booleans as quantities.
- A reservation must contain at least one product. All products must exist.
- `available = on_hand - reserved`; none of these quantities may be negative.
- Reserving increases reserved stock without changing on-hand stock.
- Committing an active reservation decreases both on-hand and reserved stock
  by its quantities. It represents a completed purchase.
- Releasing an active reservation decreases reserved stock without changing
  on-hand stock.
- Committed and released reservations remain queryable. Neither may transition
  to a different status.
- Repeating `commit` on a committed reservation, or `release` on a released
  reservation, with a **new** request ID succeeds without changing stock.
- Committing a released reservation or releasing a committed reservation fails.
- Unknown products and reservations raise errors. Reads must not create them.
- Inputs and returned snapshots must not expose mutable internal state.

## Stage 2: atomic multi-product operations

Every mutation either succeeds completely or leaves business state unchanged.

For example, if a cart requests three apples and two pears, but only one pear is
available, reserving it must not reserve any apples, create a reservation, or
consume the request ID. An invalid quantity or unknown product anywhere in a
cart has the same all-or-nothing behavior.

The invariant to preserve is:

> For each product, reserved stock equals the sum of that product's quantities
> across all ACTIVE reservations.

No particular reservation-ID format or gap-free sequence is required.

## Stage 3: idempotent retries

Use a single request-ID namespace across `reserve`, `commit`, and `release`
within one service instance. Retain successful request records for its lifetime.

Define request identity as the operation name plus its arguments, excluding
`request_id`:

- For `reserve`, dictionary insertion order does not matter. The same
  product/quantity pairs constitute the same payload.
- For `commit` and `release`, the payload is the reservation ID.
- A retry with the same request ID and identical operation/payload returns the
  **original successful response snapshot**, without executing again.
- A successful request ID reused with a different payload or operation raises
  an idempotency-conflict error and changes nothing.
- Failed requests are **not recorded**. Their IDs may be reused, with either the
  same or a different payload. A failed reservation may succeed after restocking.
- A successful replay is resolved before checking current business state.
  For example, replaying a successful `reserve` after its reservation was
  committed still returns the original `ACTIVE` response. Calling
  `get_reservation` returns its current `COMMITTED` state.
- Mutating a returned response must not affect future replay responses.

Basic argument types may be assumed correct except for the explicitly stated
ID and quantity checks. If multiple ordinary validation errors apply, you may
choose which to report first. For an already successful request ID with a
different well-formed payload, report an idempotency conflict.

## Worked example

1. Receive 5 apples and 2 pears.
2. Reserve `{"apple": 3, "pear": 2}` with request ID `cart-1`; call the returned
   reservation ID `R`. Apple stock is `(on_hand=5, reserved=3, available=2)`;
   pear stock is `(2, 2, 0)`.
3. Retry with `{"pear": 2, "apple": 3}` and `cart-1`. Return the same successful
   snapshot, including ID `R`; stock is unchanged.
4. Reserve `{"apple": 1, "pear": 1}` with `cart-2`. Fail without changing either
   product's stock.
5. Commit `R` with `purchase-1`. Apple stock becomes `(2, 0, 2)` and pear stock
   becomes `(0, 0, 0)`.
6. Retry that commit with `purchase-1`. Return its original result; stock is
   unchanged. Committing `R` with a new request ID also changes no stock.
7. Release `R` with a new request ID. Fail because it is committed.
8. Receive 1 pear, then retry the failed `cart-2` reservation. It now succeeds.
9. Reuse `cart-1` with `{"apple": 1}`. Raise an idempotency-conflict error.

## Deliverables and self-review

Write your implementation and tests, plus a short note explaining:

- Your state model and how operations maintain its invariants.
- How you enforce all-or-nothing changes and recognize equivalent retries.
- How you separate historical replay results from current reservation state.
- The time and space complexity of your main operations.

Cover success paths, exact-capacity reservations, partial-failure scenarios,
terminal-state transitions, retry conflicts, retry after failure, and mutation
of input/output objects. You choose the test cases and implementation approach.

The repository's default pytest discovery targets `apps` and `backend`, so run
your tests here explicitly, for example:

```sh
uv run pytest service/inventory/
```

## Optional follow-up (only after the core works)

Add `replace_items(reservation_id, items, request_id)` for ACTIVE reservations.
The new cart replaces the entire old cart atomically. Capacity checks may reuse
stock already held by that reservation. Failed replacements preserve the
original cart and all stock counts. Apply the same idempotency rules, and reject
replacements of terminal reservations.

Example: a product has 5 units, all reserved by one reservation. Replacing that
reservation's quantity of 5 with 4 must succeed despite initial availability
being zero.
