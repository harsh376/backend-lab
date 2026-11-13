import asyncio
import time
from itertools import pairwise

from backend.services.in_memory.rate_limiter.rate_limiter import (
    SlidingLog,
    TokenBucket,
)


def max_in_window(times: list[float], period: float) -> int:
    times = sorted(times)
    best = left = 0
    for right, t in enumerate(times):
        while times[left] <= t - period:
            left += 1
        best = max(best, right - left + 1)
    return best


async def test_first_calls_up_to_limit_do_not_wait():
    limiter = SlidingLog(limit=5, period=0.2)
    start = time.monotonic()
    for _ in range(5):
        await limiter.acquire()
    assert time.monotonic() - start < 0.05


async def test_concurrent_calls_never_exceed_limit_in_any_window():
    limiter = SlidingLog(limit=5, period=0.2)
    times: list[float] = []

    async def call():
        async with limiter:
            times.append(time.monotonic())

    start = time.monotonic()
    async with asyncio.TaskGroup() as tg:
        for _ in range(15):
            tg.create_task(call())

    assert len(times) == 15
    assert max_in_window(times, 0.2) <= 5
    # 15 calls at 5 per 0.2s fill three windows, so about 0.4s in total.
    assert 0.38 <= time.monotonic() - start < 0.6


async def test_token_bucket_allows_burst_up_to_capacity():
    bucket = TokenBucket(limit=5, period=0.2)
    start = time.monotonic()
    for _ in range(5):
        await bucket.acquire()
    assert time.monotonic() - start < 0.05


async def test_token_bucket_refills_at_steady_rate_after_burst():
    bucket = TokenBucket(limit=5, period=0.2)  # 25 tokens/s -> one every 40ms
    times: list[float] = []

    async def call():
        async with bucket:
            times.append(time.monotonic())

    start = time.monotonic()
    async with asyncio.TaskGroup() as tg:
        for _ in range(15):
            tg.create_task(call())

    assert len(times) == 15
    # 5 burst immediately, the other 10 trickle out one per 40ms: ~0.4s total.
    assert 0.38 <= time.monotonic() - start < 0.6
    gaps = [b - a for a, b in pairwise(times[5:])]
    assert all(g >= 0.035 for g in gaps)
