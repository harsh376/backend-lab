# Iterables, Iterators, Generators (sync and async)

Each is a special case of the one before it: **every generator is an iterator, and every iterator is an iterable.**

## Sync

### Iterable: something you can loop over

An object with `__iter__()`, which returns a **new iterator** on each call. Examples: `list`, `tuple`, `dict`, `set`, `str`, `range`.
It doesn't track position, so it can be looped over many times.

```python
nums = [1, 2, 3]
for x in nums: ...   # fresh iterator each time
for x in nums: ...   # works again
```

### Iterator: a cursor that remembers its position

Has `__next__()` (returns the next item or raises `StopIteration`) and `__iter__()` (returns `self`). It is **single-use**.

```python
it = iter([1, 2, 3])
next(it)   # 1
list(it)   # [2, 3]
list(it)   # []  (already used up)
```

```python
class Countdown:
    def __init__(self, start: int) -> None:
        self.current = start
    def __iter__(self) -> "Countdown":
        return self
    def __next__(self) -> int:
        if self.current <= 0:
            raise StopIteration
        self.current -= 1
        return self.current + 1
```

What a `for` loop actually does:

```python
_it = iter(obj)
while True:
    try:
        x = next(_it)
    except StopIteration:
        break
    ...
```

### Generator: an iterator written as a function

A function containing `yield`. Calling it returns a generator object (an iterator) without running the body. Each `next()` resumes the function until the next `yield`.

```python
def countdown(start: int) -> Iterator[int]:
    while start > 0:
        yield start
        start -= 1

squares = (x * x for x in range(10))   # generator expression, lazy
```

### Comparison

| | Iterable | Iterator | Generator |
|---|---|---|---|
| Methods | `__iter__` | `__iter__` + `__next__` | Both, provided automatically |
| Tracks position | No | Yes | Yes (paused frame) |
| Reusable | Yes | No | No |
| Examples | `list`, `dict`, `range` | `iter(list)`, files, `map`, `zip` | `yield` functions, `(x for x in ...)` |

### Pitfall: generators are used up after one pass

```python
e = (x for x in range(10) if x % 2 == 0)
sum(e)   # 20
max(e)   # ValueError: max() arg is an empty sequence
```

To loop more than once, make `__iter__` a generator:

```python
class Evens:
    def __init__(self, n: int) -> None:
        self.n = n
    def __iter__(self) -> Iterator[int]:
        yield from (x for x in range(self.n) if x % 2 == 0)
```

### When to use which

- **Iterable / container**: when callers need to loop over the data more than once.
- **Generator**: for streaming, large or infinite data, and lazy pipelines.
- **Hand-written iterator class**: only when the cursor needs extra methods or state (`peek()`, `reset()`).

## Async

| | Sync | Async |
|---|---|---|
| Iterable | `__iter__()` | `__aiter__()`, a **regular** `def` |
| Iterator | `__next__()` | `async def __anext__()` |
| End signal | `StopIteration` | `StopAsyncIteration` |
| Loop | `for` | `async for` |
| Builtins | `iter()`, `next()` | `aiter()`, `anext()` (3.10+) |
| Generator | `def` + `yield` | `async def` + `yield` |

```python
class Ticker:
    def __init__(self, n: int) -> None:
        self.i, self.n = 0, n
    def __aiter__(self) -> Self:            # not async
        return self
    async def __anext__(self) -> int:
        if self.i >= self.n:
            raise StopAsyncIteration
        await asyncio.sleep(0.1)
        self.i += 1
        return self.i

async def ticker(n: int) -> AsyncIterator[int]:   # async generator, the usual form
    for i in range(1, n + 1):
        await asyncio.sleep(0.1)
        yield i

async def main() -> None:
    async for t in ticker(3): ...
    squares = [x * x async for x in ticker(3)]
    first = await anext(ticker(3))
```

Generator methods change to their async forms: `.send()` → `await .asend()`, `.throw()` → `await .athrow()`, `.close()` → `await .aclose()`.

### Async gotchas

1. **Don't `await` an async generator call.** `ticker(3)` returns the generator immediately. `await ticker(3)` raises a `TypeError`.
2. **Protocols / abstract methods:** declare `def stream(self) -> AsyncIterator[T]` **without** `async`. An `async def` without `yield` is typed as a coroutine that returns an iterator, which doesn't match async-generator implementations.
3. **Cleanup is not immediate.** After `break`, `finally` blocks run only when the generator is finalized. Close it explicitly:
   ```python
   async with contextlib.aclosing(read_rows(conn)) as rows:
       async for row in rows:
           if done(row):
               break
   ```
4. **Plain `for` can't consume an async iterator.** To pass a sync iterable to an async API, wrap it in an `async def` that yields each item.
5. **`async for` is sequential.** For concurrency, use `asyncio.gather`, `TaskGroup`, or a producer/consumer queue.

## Type hints

Import from `collections.abc` (the `typing.*` aliases are deprecated since 3.9).

**Rule of thumb:** for parameters, ask for the least you need (`Iterable[T]`). For return types, say exactly what you return (`Iterator[T]`).

| Situation | Sync hint | Async hint |
|---|---|---|
| Argument you loop over once | `Iterable[T]` | `AsyncIterable[T]` |
| Argument you need `len()` of or loop over more than once | `Collection[T]` / `Sequence[T]` | — |
| Generator that only yields | `Iterator[T]` | `AsyncIterator[T]` |
| Generator using send / return value | `Generator[Y, S, R]` | `AsyncGenerator[Y, S]` (no return type) |
| `__iter__` / `__aiter__` | `-> Iterator[T]` (or `Self`) | `-> AsyncIterator[T]` (or `Self`) |
| `__next__` / `__anext__` | `-> T` | `async def ... -> T` |

- A plain generator `Generator[int, None, None]` is equivalent to `Iterator[int]`.
- On Python 3.13+, the send/return parameters default to `None`, so `Generator[int]` and `AsyncGenerator[int]` work.
- Async generators can't `return value`, which is why `AsyncGenerator` has no return-type parameter.

```python
def running_avg() -> Generator[float, float, str]:
    total = count = 0
    while True:
        value = yield (total / count if count else 0.0)
        if value is None:
            return "done"
        total += value
        count += 1
```
