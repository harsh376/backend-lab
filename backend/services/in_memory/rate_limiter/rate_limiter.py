"""A minimal async rate limiter: at most `limit` calls in any rolling `period`.

limiter = SlidingLog(limit=100, period=1.0)   # Terminal: 100 req/s per connection
async with limiter:
    await client.get(...)
"""

import asyncio
import time
from collections import deque


class SlidingLog:
    def __init__(self, limit: int, period: float = 1.0):
        self.limit = limit
        self.period = period
        self._calls: deque[float] = deque()  # start times of recent calls
        self._lock = asyncio.Lock()  # waiters go through one at a time, in order

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            # Forget calls that have left the window.
            while self._calls and self._calls[0] <= now - self.period:
                self._calls.popleft()
            if len(self._calls) >= self.limit:
                # Wait until the oldest call leaves the window, freeing one slot.
                await asyncio.sleep(self._calls[0] + self.period - now)
                self._calls.popleft()
            self._calls.append(time.monotonic())

    async def __aenter__(self) -> "SlidingLog":
        await self.acquire()
        return self

    async def __aexit__(self, *exc) -> None:
        pass


class TokenBucket:
    """Token bucket: refills at `limit / period` tokens per second, holds at most
    `capacity` tokens (default `limit`). Each call spends one token.

    Same interface as SlidingLog, so it's a drop-in swap. Unlike the sliding log,
    it doesn't guarantee "<= limit in any rolling period": after a full burst, the
    refill can let up to ~2x limit through in one rolling period. What it does
    guarantee is the long-run average rate, with bursts capped at `capacity`.
    """

    def __init__(self, limit: int, period: float = 1.0, capacity: int | None = None):
        self.rate = limit / period  # tokens added per second
        self.capacity = capacity if capacity is not None else limit
        self._tokens = float(self.capacity)  # start full: allow an initial burst
        self._last = time.monotonic()
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        self._tokens = min(self.capacity, self._tokens + (now - self._last) * self.rate)
        self._last = now

    async def acquire(self) -> None:
        async with self._lock:
            self._refill()
            if self._tokens < 1:
                # Sleep exactly long enough for the missing fraction of a token.
                await asyncio.sleep((1 - self._tokens) / self.rate)
                self._refill()
            self._tokens -= 1

    async def __aenter__(self) -> "TokenBucket":
        await self.acquire()
        return self

    async def __aexit__(self, *exc) -> None:
        pass
