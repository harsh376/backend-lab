# In-memory service practice — learnings

Distilled from the 14 exercises in this directory. Sections:

1. [Exercise map](#1-exercise-map)
2. [Interview playbook](#2-interview-playbook)
3. [Recurring patterns](#3-recurring-patterns)
4. [Python quirks that bit (or nearly bit)](#4-python-quirks)
5. [Templates](#5-templates)
6. [Testing checklist and idioms](#6-testing)
7. [Production follow-up talking points](#7-production-follow-ups)
8. [Bugs found in my own code](#8-bugs-found-in-my-own-code)
9. [Using AI during the exercise](#9-using-ai-during-the-exercise)

---

## 1. Exercise map

| Exercise | Core idea | Key data structures / techniques |
| --- | --- | --- |
| `catalog`, `book_inventory` | Search → filter → sort → paginate | list comprehension filter, tuple sort keys, slicing, `total` before paging |
| `order_analytics` | Report over a time range (debugging) | half-open `[start, end)`, `Decimal.quantize(ROUND_HALF_UP)`, metrics independent of paging |
| `inventory` | Multi-item atomic reserve / commit / release + idempotency | validate-all-then-mutate, `frozenset(items.items())` payload, `MappingProxyType`, request log |
| `idempotent_checkout` | Retry-safe checkout | idempotency key → stored response; replay before business checks |
| `inventory_import` | Batch import: partial / atomic / dry run, patch semantics | validate → plan → apply, `Counter` for duplicates, one-based row errors |
| `job_scheduler` | `run_due(now)` + retries with delay | select-due → sort → execute → update, `try/except/else`, injected executor |
| `due_date_notifications` | Time-triggered, at-most-once notifications | catch-up (`scheduled <= now`), deterministic IDs as dedupe keys, monotonic `now` |
| `reservation` | Slots with capacity + expiring holds | lazy expiry on every call, `RLock`, `frozenset` membership, custom error hierarchy |
| `fifo_reservation_waitlist` | FIFO allocation of scarce copies | status state machine, `itertools.count`, `deque` |
| `priority_boarding` | Two-tier FIFO (priority before regular) | two `deque`s per stop, drain priority first up to capacity |
| `lru_cache` | LRU eviction | `OrderedDict.move_to_end` / `popitem(last=False)` |
| `in_memory_file_system` | Path tree | trie of `Node`s, path validation, iterative DFS for listing |
| `spreadsheet` | Cells with `A1 + 5 - B2` formulas | regex tokenizer, DFS with memo + cycle detection, recursive → explicit stack |
| `title.py`, `user_list.py` | Async service over a repository | DI (repo, metrics, logger), catch → record outcome → bare `raise` |

---

## 2. Interview playbook

The briefs all grade the same things. Use this sequence every time.

**Clarify first (≈8 min).** Ask about:

- **IDs:** Who generates them? Case-sensitive? Trim or not? Unique for the instance's lifetime, even after deletion or a terminal state?
- **Types:** Reject `bool` as `int`? Floats? Numeric strings? Is zero valid?
- **Lifecycle:** What are the states and allowed transitions? Is repeating a terminal action a no-op or an error? Can a terminal record come back to life?
- **Ordering:** What is the primary key? What breaks ties? Does the tie-break flip with `desc`?
- **Boundaries:** `<=` or `<` at `now`? Half-open ranges? `limit=0`? Offset past the end?
- **Idempotency:** What counts as "the same request"? Are failed requests remembered? Is the replay resolved before current-state checks?
- **Atomicity:** Is it all-or-nothing? Do failed calls leave state untouched?
- **Returns:** Which result types? Must returned data be protected from caller mutation? What does a mutation return (ID, snapshot, list of newly affected records)?
- **Errors:** Which exception types? Which error wins when several apply?
- **Time:** Is `now` passed in? Is it guaranteed nondecreasing? What happens if it goes backwards?

**State the contract back** in 5–8 bullets before coding. Most review points in the briefs are about rules that were never clarified.

**Error contract (decide upfront, don't defer).** Always use the same five classes from §5.1: `ServiceError` as the base, plus `ValidationError` (bad input), `NotFoundError` (unknown ID), `AlreadyExistsError` (duplicate ID) and `ConflictError` (bad transition, idempotency conflict, insufficient stock). The message carries the specifics, e.g. `raise NotFoundError("Book does not exist")`. Say this aloud as your error contract. Add a specific subclass only if the brief needs callers to tell cases apart.

**Implement** in this order: types → errors → store → validators → happy path → edge cases.

**Test** behaviour and boundaries, not implementation details (see §6).

**Close** by covering invariants, complexity, and what changes for a DB or concurrency (see §7).

---

## 3. Recurring patterns

### 3.1 Service shape

- A `dict[ID, Record]` is the source of truth. Add secondary indexes only when needed.
- Records are `@dataclass(frozen=True)`. Update with `self.store[id] = replace(rec, field=new)`.
- Validate first, check existence and conflicts next, mutate last. Every failure path then leaves state unchanged for free.
- Private helpers `_validate_*`, `_get_or_raise`.

### 3.2 Designing normalized state

Treat the store like database tables:

- **One `dict[ID, frozen Record]` per entity that has an ID.**
- **Put links on the child:** `Reservation.title_id`, not a list of IDs on `Title`. Find a title's children by scanning, which is fine at interview scale.
- **Derive instead of storing:** use a `@property` or a count over records (`available = on_hand - reserved`; reserved = number of `RESERVED` records).
- **Keep terminal records and give them a status.** Don't delete them; briefs want history to stay inspectable.
- **Store each fact in one place.** A duplicated fact has to be kept in sync on every transition, and that's where bugs come from.
- **Add a secondary index only when an operation needs it,** and update it in the same helper that changes the main store.

Example (`fifo_reservation_waitlist`): only titles and reservations have identity, so the state is two dicts and a sequence.

```python
@dataclass(frozen=True)
class Title:
    id_: TitleID
    available: int


@dataclass(frozen=True)
class Reservation:
    id_: ReservationID
    title_id: TitleID          # link lives on the child
    patron_id: PatronID
    status: Status             # WAITING | RESERVED | COLLECTED | CANCELED


class WaitlistService:
    def __init__(self) -> None:
        self._titles: dict[TitleID, Title] = {}
        # Insertion order == successful join order, so this dict *is* the FIFO queue.
        self._reservations: dict[ReservationID, Reservation] = {}
        self._seq = count(1)
        # Invariant per title: initial + added == available + #RESERVED + #COLLECTED

    def _for_title(self, title_id: TitleID, *statuses: Status) -> list[Reservation]:
        return [
            r for r in self._reservations.values()
            if r.title_id == title_id and r.status in statuses
        ]
```

What's deliberately **not** stored:

| Tempting field | Why leave it out |
| --- | --- |
| `Title.reserved: int` | It's the count of `RESERVED` records. A stored copy can drift out of sync. |
| `Title.waitlist: deque[ReservationID]` | It's the `WAITING` records in dict order. A separate copy must be updated on every join, cancel and allocate. |
| Deleting cancelled or collected records | Terminal records must stay queryable, and a rejoin gets a new ID anyway. |

What this gives you for free:

- **Rejoin goes to the back:** a new ID is appended at the end of the dict.
- **FIFO allocation is a slice:** `self._for_title(t, "WAITING")[: title.available]`.
- **Each transition updates at most one other field** (`available` on cancelling a `RESERVED` reservation).

The original implementation stored reserved IDs on `Title` *and* a status on each `Reservation`. As a result, `cancel` and `collect` had to update both, which they did by mutating a deque inside a frozen dataclass, and `allocate` needed an O(n·m) second pass.

### 3.3 Search / filter / sort / paginate (`catalog`, `book_inventory`, `order_analytics`)

- Order of operations: filter → sort → `total = len(matches)` → slice `[offset : offset + limit]`.
- Summary metrics (total, revenue, average) are computed on the full match set, never on the page.
- Build a deterministic tie-break into the key: `(p.name.casefold(), p.id_)`.
- Tie-break stays ascending while the primary sort is `desc`: either use two stable sorts (sort by ID, then by field with `reverse=True`), or negate numeric keys.
- `limit=0` and an offset past the end return an empty page with the correct total. Slicing already does this, but you must reject negative offsets yourself (see §4).

### 3.4 Idempotency (`inventory`, `idempotent_checkout`, `due_date_notifications`)

```
replay = requests.get(request_id)
if replay: if same op & payload → return stored response; else → conflict error
... do the work (may raise → nothing recorded) ...
requests[request_id] = Request(op, payload, response); return response
```

- **Payload identity:** Use a hashable, order-insensitive form such as `frozenset(items.items())`. Include the operation name so one ID can't be reused across operations.
- **Replay before business checks:** A retry after stock hits zero must still return the original success.
- **Store the response, not a pointer to live state:** Frozen snapshots make this free. A replay returns the *original* status even if the record has moved on since.
- **Failed requests are not recorded:** The ID stays reusable.
- **Successful no-ops also claim the ID:** For example, committing an already-committed reservation.
- **Derived dedupe keys:** Notification ID = `f"{loan_id}--{kind}"` gives at-most-once without a request ID.

### 3.5 Atomic multi-item operations (`inventory`, `inventory_import`)

Two phases:

1. **Validate everything** and build the full plan. No writes happen here.
2. **Apply** the plan in a loop that cannot fail.

For import-style work, use three phases: **validate → plan → apply**, with switches for `dry_run` (skip apply) and `atomic` (skip apply if there are any errors). Planned counts are always reported. Applied counts are zero when apply was skipped.

### 3.6 State machines (`inventory`, `fifo_reservation_waitlist`, `job_scheduler`)

- Use a `Literal` status. Write the transition table down before coding:
  `WAITING → RESERVED → COLLECTED`, `WAITING|RESERVED → CANCELLED`.
- Repeating a terminal action (cancel a cancelled record) is a **successful no-op**. A conflicting transition (cancel a collected record) is an **error**.
- Every transition updates the counters it affects (available/reserved) in the same step. State the invariant, e.g. `initial + added == available + reserved + collected`.

### 3.7 Time-driven processing (`job_scheduler`, `due_date_notifications`, `reservation`)

- `now` is always a parameter. There is no real clock.
- **Catch-up semantics:** An item is eligible when `scheduled <= now`. Don't require exact-time calls.
- Select the due items, sort them deterministically (`(time, id)`), then process them. Don't mutate the dict while iterating it.
- **At most one attempt per item per call:** Retries move to `now + delay`, so they fall outside the current `now`.
- **Monotonic `now`:** Store `_last_processed_at` and raise if a call goes backwards.
- **Lazy expiry:** Purge expired holds at the start of each public call (`_expire_holds(now)`) instead of running a background job.
- Return only the items **newly** processed in this call. Keep the history inspectable.

### 3.8 Queues and allocation (`fifo_reservation_waitlist`, `priority_boarding`)

- FIFO order = successful call order. Use a `deque`, or rely on dict insertion order plus a status filter.
- Two-tier priority means two deques. Drain `priority` before `regular`, and stop when capacity runs out.
- "Allocate as many as fit": `n = min(available, len(waiting))`.
- Keep a `seen: set` for "only once per instance" rules instead of scanning every queue.

### 3.9 Trees and graphs (`in_memory_file_system`, `spreadsheet`)

- Path → `parts = path.split("/")[1:]`. Reject `""`, `.`, `..`. Walk the path with an optional `create_missing`.
- Distinguish the three failures: "missing", "is a file where a dir is expected", and "duplicate".
- DFS over dependencies needs `cache` (memo) and `visited` (cycle detection). **Check the cache before `visited`**, or a diamond dependency looks like a cycle.
- Validate before committing: build the new cell, evaluate it to detect cycles, and only then store it.
- Converting recursion to iteration: push `(frame, next_index, partial_total, pending_sign)` onto a stack, i.e. suspend and resume frames.

### 3.10 Async repository service (`title.py`, `user_list.py`)

```python
try:
    result = await self._repository.op(...)
except KnownError:
    self._record("op", "not_found", id_, request_id)
    raise                      # bare raise keeps the traceback
self._record("op", "success", id_, request_id)
return result
```

Dependencies are injected through `__init__`. Logging is structured through `extra={...}`. Outcomes use a fixed vocabulary.

---

## 4. Python quirks

| Quirk | Consequence | Fix / idiom |
| --- | --- | --- |
| `bool` is a subclass of `int` | `isinstance(True, int)` is `True`, so `True` passes as quantity 1 | `type(x) is int`, or `isinstance(x, bool) or not isinstance(x, int)` |
| `"".isspace()` is `False` | An `isspace()` check alone lets `""` through | `not isinstance(s, str) or not s.strip()` |
| `frozen=True` is **shallow** | A frozen dataclass holding a `deque`, `dict` or `list` can still be mutated in place (`title.reservation_ids.remove(...)`) | Store `tuple`/`frozenset`, or copy before mutating and `replace(...)` |
| `MappingProxyType` is a *view* and shallow | Changes to the underlying dict show through; nested values stay mutable | Wrap a fresh `dict(...)` you don't keep, and deep-copy nested payloads |
| Mutable defaults | `x: list = []` in a dataclass raises `ValueError` | `field(default_factory=list)` |
| `d.get(k) is None` | Can't tell "missing" from "stored `None`" (the LRU raises `KeyError` for a `None` value) | `if k not in d` |
| `Literal[...]` isn't enforced at runtime | A bad `sort_by` silently falls through | `if value not in ("a", "b"): raise ValueError` |
| Negative slice indices wrap | `xs[-1:1]` doesn't fail, it gives a wrong page | Validate `offset >= 0 and limit >= 0` |
| Out-of-range slices don't fail | `[1,2,3][5:10] == []` | Good: an offset past the end gives an empty page for free |
| `sort` is stable, `reverse=True` too | Equal keys keep their prior order even when reversed | Two-pass sort: tie-break key first, then primary key |
| `round(2.5) == 2` | Banker's rounding | `Decimal(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)` |
| `int()` is lenient | `int(" 7 ")` and `int("1_000")` both succeed | Use a regex such as `re.fullmatch(r"[+-]?\d+", s)` if strictness matters |
| `str.lower()` vs `casefold()` | `casefold` handles ß and other Unicode cases | Use `casefold()` for case-insensitive matching |
| Dicts keep insertion order (3.7+) | Usable as a FIFO record log | Use `OrderedDict` only when you need `move_to_end` or `popitem(last=False)` |
| Recursion limit ≈ 1000 | Deep dependency chains crash the recursive DFS | Use an explicit stack |
| `threading.Lock` isn't reentrant | A public method calling another locked public method deadlocks | `RLock` (as in `reservation.confirm_hold → cancel_hold`) |
| `except Exception` in a runner | Needed so one failing job doesn't stop the batch | `try/except/else`: the `else` block is the success path |
| Iterable arguments may be generators | Iterating twice silently yields nothing the second time | `rows = list(rows)` at the top |
| `frozenset(d.items())` | Requires hashable values | Fine for `dict[str, int]` |
| Chained comparisons | `0 <= refunded <= gross` is valid and readable | — |

Handy stdlib: `dataclasses.replace`, `itertools.count()` for IDs (`next(seq)`), `collections.Counter`, `dict.setdefault(k, []).append(v)`, `enumerate(rows, start=1)`, `f"{x!r}"`, PEP 695 `type Alias = ...`, `typing.Self`, keyword-only args with `*`.

---

## 5. Templates

### 5.1 Service skeleton

```python
from dataclasses import dataclass, replace
from itertools import count
from typing import Literal

type ItemID = str
type Status = Literal["ACTIVE", "DONE", "CANCELLED"]


# --- errors: one base, specific subclasses (optionally also ValueError) ---
class ServiceError(Exception): ...
class ValidationError(ServiceError, ValueError): ...
class NotFoundError(ServiceError): ...
class AlreadyExistsError(ServiceError): ...
class ConflictError(ServiceError): ...          # bad transition / idempotency


# --- immutable records: safe to return and to cache ---
@dataclass(frozen=True)
class Item:
    id_: ItemID
    quantity: int
    status: Status = "ACTIVE"


class ItemService:
    def __init__(self) -> None:
        self._items: dict[ItemID, Item] = {}
        self._seq = count(1)

    # --- public API ---
    def create(self, item_id: ItemID, quantity: int) -> Item:
        _require_str(item_id, "item_id")
        _require_int(quantity, "quantity", minimum=0)
        if item_id in self._items:
            raise AlreadyExistsError(item_id)
        item = self._items[item_id] = Item(item_id, quantity)
        return item

    def get(self, item_id: ItemID) -> Item:
        return self._get(item_id)

    def cancel(self, item_id: ItemID) -> Item:
        item = self._get(item_id)
        if item.status == "CANCELLED":
            return item                               # idempotent terminal no-op
        if item.status != "ACTIVE":
            raise ConflictError(f"cannot cancel {item.status}")
        item = self._items[item_id] = replace(item, status="CANCELLED")
        return item

    # --- helpers ---
    def _get(self, item_id: ItemID) -> Item:
        item = self._items.get(item_id)
        if item is None:
            raise NotFoundError(item_id)
        return item


def _require_str(value, name: str) -> None:
    if not isinstance(value, str) or not value:        # add .strip() if blank is invalid
        raise ValidationError(f"{name} must be a nonempty string")


def _require_int(value, name: str, *, minimum: int) -> None:
    if type(value) is not int or value < minimum:       # rejects bool
        raise ValidationError(f"{name} must be an integer >= {minimum}")


def _require_choice(value, name: str, choices: tuple[str, ...]) -> None:
    if value not in choices:
        raise ValidationError(f"{name} must be one of {choices}")
```

### 5.2 Search with pagination

```python
@dataclass(frozen=True)
class Page[T]:
    items: tuple[T, ...]
    total: int

def search(self, query="", category=None, sort_by="name", order="asc",
           offset=0, limit=20) -> Page[Item]:
    _require_choice(sort_by, "sort_by", ("name", "price"))
    _require_choice(order, "order", ("asc", "desc"))
    _require_int(offset, "offset", minimum=0)
    _require_int(limit, "limit", minimum=0)

    q = query.casefold()
    matches = [
        p for p in self._items.values()
        if q in p.name.casefold()
        and (category is None or p.category == category)
    ]
    matches.sort(key=lambda p: p.id_)                             # tie-break (always asc)
    key = (lambda p: p.name.casefold()) if sort_by == "name" else (lambda p: p.price)
    matches.sort(key=key, reverse=order == "desc")                # stable
    return Page(tuple(matches[offset:offset + limit]), total=len(matches))
```

### 5.3 Idempotent mutation

```python
@dataclass(frozen=True)
class RequestRecord:
    op: str
    payload: Hashable
    response: object

def _replay(self, request_id, op, payload):
    rec = self._requests.get(request_id)
    if rec is None:
        return None
    if rec.op != op or rec.payload != payload:
        raise ConflictError("request_id reused with different operation/payload")
    return rec.response

def reserve(self, items: dict[str, int], request_id: str) -> Reservation:
    _require_str(request_id, "request_id")
    payload = frozenset(items.items())
    if (cached := self._replay(request_id, "reserve", payload)) is not None:
        return cached
    plan = self._validate_items(items)            # raises -> nothing recorded
    result = self._apply_reserve(plan)            # cannot fail
    self._requests[request_id] = RequestRecord("reserve", payload, result)
    return result
```

### 5.4 Validate → plan → apply (batch, atomic, dry run)

```python
def import_rows(self, rows, *, atomic=False, dry_run=False) -> ImportResult:
    rows = list(rows)
    valid, errors = {}, {}
    for n, row in enumerate(rows, start=1):
        product, errs = self._validate(row)
        if errs: errors[n] = errs
        else:    valid[n] = product
    # cross-row rules (duplicates) -> move rows from valid to errors
    to_create = [p for p in valid.values() if p.id_ not in self._items]
    to_update = [p for p in valid.values() if p.id_ in self._items]
    apply = not dry_run and not (atomic and errors)
    if apply:
        for p in to_create + to_update:
            self._items[p.id_] = p
    return ImportResult(errors=..., planned=(len(to_create), len(to_update)),
                        applied=(len(to_create), len(to_update)) if apply else (0, 0))
```

### 5.5 Time-driven processor

```python
def run_due(self, now: int) -> list[JobID]:
    _require_int(now, "now", minimum=0)
    if self._last_now is not None and now < self._last_now:
        raise ValidationError("now must be nondecreasing")
    self._last_now = now

    due = sorted(
        (j for j in self._jobs.values() if j.status == "pending" and j.run_at <= now),
        key=lambda j: (j.run_at, j.id_),
    )                                         # snapshot first, then mutate
    ran = []
    for job in due:
        try:
            self._executor(deepcopy(job.payload))
        except Exception as e:
            job = self._on_failure(job, now, e)   # retry at now + delay, or terminal
        else:
            job = replace(job, status="succeeded", attempts=job.attempts + 1)
        self._jobs[job.id_] = job
        ran.append(job.id_)
    return ran
```

### 5.6 LRU cache

```python
class LRUCache:
    def __init__(self, capacity: int):
        if capacity <= 0: raise ValueError("capacity must be positive")
        self._cap, self._d = capacity, OrderedDict()

    def get(self, key):
        if key not in self._d: raise KeyError(key)
        self._d.move_to_end(key)
        return self._d[key]

    def set(self, key, value):
        if key in self._d: self._d.move_to_end(key)
        self._d[key] = value
        if len(self._d) > self._cap: self._d.popitem(last=False)
```

### 5.7 DFS with memo and cycle detection (iterative)

```python
def evaluate(self, root_id):
    cache, visiting = {}, set()
    stack = [(root_id, False)]
    while stack:
        node, expanded = stack.pop()
        if node in cache: continue
        if expanded:
            cache[node] = combine(cache[d] for d in deps(node))
            visiting.discard(node)
            continue
        if node in visiting: raise CycleError(node)
        visiting.add(node)
        stack.append((node, True))
        stack.extend((d, False) for d in deps(node) if d not in cache)
    return cache[root_id]
```

---

## 6. Testing

**Checklist:** these behaviours come up in almost every brief.

- Happy path, including an end-to-end "worked example" test copied from the brief.
- Boundaries: exactly at `now`, at `now - 1`, at capacity, at capacity + 1, zero stock, `limit=0`, offset past the end.
- Deterministic ordering: equal primary keys, the tie-break under `desc`, and the exact order of IDs (assert IDs, not only counts).
- Duplicate IDs and unknown IDs (unknown IDs must fail even when the operation would be a no-op).
- Invalid input: `True` as an int, `""`, whitespace, negative numbers, unsupported enum values.
- **Failed operations leave state unchanged:** snapshot the state before, assert equality after.
- **Mutation isolation:** mutate the input after the call, mutate the returned object, then re-read.
- Idempotency: same key and payload → same response; different payload → conflict; failed key → reusable; replay after the state has moved on.
- Lifecycle: every allowed transition, repeated terminal actions (no-op), forbidden transitions.
- Invariant helper asserted after each step (e.g. `reserved == sum(active reservations)`).

**Idioms**

```python
@pytest.fixture
def service():
    s = InventoryService(); s.receive_stock("apple", 5); return s

@pytest.mark.parametrize("bad", [0, -1, True, 1.5, "3"])
def test_rejects_bad_quantity(service, bad):
    before = service.get_stock("apple")
    with pytest.raises(ValidationError, match="quantity"):
        service.receive_stock("apple", bad)
    assert service.get_stock("apple") == before          # state preserved

def test_returned_record_is_immutable(service):
    with pytest.raises(FrozenInstanceError):
        service.get_stock("apple").on_hand = 999
```

- `pytest.raises(..., match=...)` takes a **regex**. Escape `(`, `.`, `?`.
- Prefer specific exception classes over `Exception`. A broad `pytest.raises(Exception)` needs `# noqa: B017` and can hide typos.
- Frozen dataclasses compare by value, so you can assert a whole record or state dict in one line.
- Run one suite: `uv run pytest apps/api/services/<name>/`.

---

## 7. Production follow-ups

Every brief ends with "what would change for a database or concurrency?". Short answers:

| Topic | Answer |
| --- | --- |
| Complexity | Searches and scans are O(n) plus O(k log k) sorting. Name the index you'd add (secondary dict, heap by `run_at`, `seen` set). |
| Search in a DB | `WHERE` filters, composite index matching `ORDER BY (field, id)`, `COUNT(*)` or a window function for the total, keyset pagination instead of offset for deep pages. |
| Uniqueness | Unique constraint on the ID or the natural key (`loan_id, kind`). Insert and catch the violation instead of check-then-insert. |
| Idempotency | Table `idempotency_keys(key PK, op, payload_hash, response, created_at)`, written in the **same transaction** as the business change. Handle two in-flight requests with the same key (insert a pending row first, or lock). Add a TTL. |
| Atomic stock | One transaction with `UPDATE ... SET available = available - q WHERE id = ? AND available >= q` (check the row count), or `SELECT ... FOR UPDATE` in a consistent ID order to avoid deadlocks. |
| Scheduler / notifications | `SELECT ... FOR UPDATE SKIP LOCKED` on due rows, lease/visibility timeouts, at-least-once delivery plus idempotent consumers, a transactional outbox for sending. |
| FIFO / priority queues | A DB sequence or `created_at` plus an ID tie-break; row locks when allocating; fairness vs. strict priority (starvation, aging). |
| In-process concurrency | A lock around each public method (`RLock` if methods call each other), or one lock per aggregate (per title or slot). |
| Time | Inject a clock; store UTC epoch values; use half-open ranges. |

---

## 8. Bugs found in my own code

Things to avoid next time:

- **`lru_cache.get`** uses `value is None` to detect a miss, so a stored `None` raises `KeyError`. Use `if key not in self.cache`.
- **`priority_boarding`**, **`fifo_reservation_waitlist`**, **`in_memory_file_system`** use frozen dataclasses that hold `deque`s and `dict`s, which are mutated in place (`popleft`, `remove`, `children[...] =`). The `replace(...)` afterwards is cosmetic; the "frozen" guarantee isn't real.
- **`priority_boarding.add_passenger`** scans every stop and bus for duplicates (O(total passengers)). The later `if passenger_id in priority: return` is dead code. A `seen_passengers: set` fixes both.
- **`idempotent_checkout.checkout`** checks that the book exists *before* the replay lookup, so reusing a key with an unknown book gives "Book does not exist" instead of an idempotency conflict. The key is also allowed to be `""`, and whitespace-only IDs are rejected even though the brief allows them.
- **`inventory.get_stock`** returns `None` for unknown products, but the brief says unknown products raise.
- **`job_scheduler`**: `MappingProxyType(dict(payload))` is shallow, so nested payload data can still be mutated by the caller or the executor (use `deepcopy`). `Job.status` is typed `str` instead of `JobStatus`, and `job_id`/`run_at` aren't validated.
- **`book_inventory`**: `_validate_non_negative_integer` checks `> 0` and is never used. Pagination errors are bare `Exception("Bad offset")`, while other errors use custom classes. Pick one error style per service.
- **`due_date_notifications`**: the notification ID suffix `--due_at` doesn't match the kind `due_now`. Keep IDs derived from the same value.
- **`fifo_reservation_waitlist.allocate`**: `r_id in upgraded_reservation_ids` is a membership test on a `deque` (O(n·m)), and every error is a bare `Exception`. The status is spelled `CANCELLED` but the brief says `CANCELED`.
- **`reservation.confirm_hold`** cancels the hold and *then* creates the reservation. If creation raised, the hold would already be gone. Do the fallible step first, or validate up front.
- **General:** error style varies across exercises (bare `Exception`, one class per field, `ValueError`). The `reservation.py` hierarchy (a base `ServiceError`, specific subclasses, `ValueError` mixed in for validation) is the one to reuse.

---

## 9. Using AI during the exercise

Don't paste the brief into the AI. The assessment grades clarification, design, invariants, tests and trade-offs. If the AI makes those calls, you've handed over the part being tested. With a slow, weaker model, a big prompt also means a long wait and output you have to debug.

**Your role vs. the AI's role.** You're the tech lead and the AI is a fast but careless junior. You decide the contract, data model, error types and core logic. The AI types the well-specified, low-risk parts. Review everything it writes as if it were a PR.

### Good uses (small, specified, quick to check)

- **Boilerplate:** exception classes, frozen dataclasses from a field list, `Literal` aliases, validator helpers.
- **Test bodies:** you write the test names, it fills in the bodies.
- **Parametrize tables:** e.g. invalid quantities `0, -1, True, 1.5, "3"`.
- **Lookups:** `OrderedDict` eviction, a tokenizer regex, `Decimal` rounding syntax.
- **One contained function**, after you've fixed its signature and rules.
- **Review:** "Here are my contract bullets and test names. Which bullets have no test?"
- **Explaining a traceback** when you've been stuck for more than 2 minutes.

### Avoid

- Pasting the brief, or asking for "the service".
- Letting it decide error semantics, ordering, or idempotency rules. Those are your clarification outcomes.
- Large rewrites ("refactor this to support retries"). You can't verify them in time.
- Having it write the core algorithm (allocation, replay check, plan/apply). That's what they'll ask you to explain.

### Prompting a slow, weak model

1. **One function or one block per request.** Shorter output comes back faster.
2. **Give it the exact signature, types and rules.** You make the decisions; it transcribes them.
   ```
   Python 3.12. Write only this method, no explanation:
   def cancel(self, reservation_id: int) -> Reservation
   - self._reservations: dict[int, Reservation] (frozen dataclass, update via dataclasses.replace)
   - unknown id -> raise NotFoundError
   - CANCELLED -> return as-is (no-op)
   - WAITING -> set CANCELLED
   - RESERVED -> set CANCELLED and increment self._titles[title_id].available by 1 (replace)
   - COLLECTED -> raise ConflictError
   Validate everything before mutating anything.
   ```
3. **Ask for code only:** "no explanation", "only the changed function".
4. **Don't wait idle.** Send the request, then write the next test or validator while it generates.
5. **Know when to stop.** If it takes about 60s or more, or is wrong twice, write it yourself. That's what the templates in §5 are for.

### Giving the AI your style

Weak models copy code they're shown much better than they follow written rules. So show your style instead of describing it.

**1. Write the skeleton yourself first (about 3 minutes).** Before prompting, type the type aliases, frozen dataclasses, error classes, `__init__` stores, and **one** complete method with its validation. Then prompt with "Follow the style of the code above." That example method teaches it your conventions, and it's design work you should own anyway.

**2. Keep a short style header you know by heart.** Paste it once per session, or above each prompt if the tool has no history:

```
Style rules:
- Python 3.12. `type X = ...` aliases, Literal for statuses.
- Records: @dataclass(frozen=True), id field named `id_`, only immutable fields (tuple/frozenset).
- State: dict[ID, Record] on the service; update via `self._x[id] = replace(rec, ...)`.
- Validate all inputs first, then check existence/conflicts, then mutate.
- Ints: `type(x) is int` (reject bool). Strings: nonempty, not trimmed unless told.
- Errors: subclasses of ServiceError (ValidationError, NotFoundError, AlreadyExistsError, ConflictError). Never bare Exception.
- IDs from itertools.count(). No comments or docstrings unless asked.
```

Settle the inconsistencies in the practice code (`id_` vs `book_id`, bare `Exception` vs custom errors, `_x` vs `x` stores) so the header and your habits match. The header above follows the `reservation.py` style.

**3. Put the style into the prompt itself.**

- **Give it the signature**, e.g. `def cancel(self, reservation_id: ReservationID) -> Reservation:`. The names, types and return shape then already follow your conventions.
- **Paste only what the method touches:** the relevant dataclass and one similar method, not the whole file. This keeps a slow model fast.
- **Name the helpers to reuse**, e.g. "use `self._get_reservation` and `_require_int`". Otherwise it writes its own inline versions.

**When it drifts anyway:** fix small style issues by hand, such as `isinstance` instead of `type(...) is`, or `ValueError` instead of your error class. Re-prompting a slow model costs more than the edit. Re-prompt only when the logic is wrong.

**Practice:** in the practice drill, paste the header and your skeleton, then track how often the output needs edits. Tune the header until it rarely does, then memorise it.

### Checking AI output

These are the usual weak-model mistakes, and they overlap with §8:

- `isinstance(x, int)`, which accepts `True`.
- A sort key with no tie-break, or a tie-break that flips under `desc`.
- Mutating state before all validation is done.
- Returning internal lists or dicts, or mutable containers inside frozen dataclasses.
- `d.get(k) is None` used as a missing-key check.
- Boundary slips: `<` vs `<=` against `now`, `limit=0`, a negative offset.
- Tests that assert counts instead of exact IDs and order.

Run the tests straight after pasting. Never paste code you haven't read.

### Narrate your decisions

Say your choices out loud so AI use looks like judgement, not dependence:

- "Exceptions are boilerplate, so I'll let the AI write them. I'll write the allocation logic myself because that's where the invariants are."
- "It used `isinstance`, which accepts booleans. Switching to `type(x) is int`."

### 60-minute split

| Phase | Who does what |
| --- | --- |
| Clarify (8 min) | You, no AI. At most, privately ask it for edge cases you missed. |
| Model + skeleton (5 min) | You pick the types; the AI writes the dataclasses and exceptions. |
| Core logic (25 min) | You write it; the AI does small helpers and lookups. |
| Tests (15 min) | You write the test names from the contract bullets; the AI fills in bodies; you check the assertions. |
| Review (5 min) | You ask the AI which bullets are untested and to review your diff against the contract; you explain trade-offs. |

### Practice drill

Redo `idempotent_checkout` and `job_scheduler` with a small, fast model (e.g. Haiku 4.5), using the AI only for the "good uses" above. Track how long you spend waiting versus typing, so you learn where it actually saves time.
