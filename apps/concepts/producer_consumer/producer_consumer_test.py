import asyncio

import pytest

from apps.concepts.producer_consumer.producer_consumer import ProducerConsumer


async def test_every_item_is_handled_once():
    handled = []

    async def handle(item: int) -> None:
        await asyncio.sleep(0)
        handled.append(item)

    await ProducerConsumer(handle).run(range(50))

    assert sorted(handled) == list(range(50))


async def test_async_iterable_source():
    async def source():
        for item in range(5):
            yield item

    handled = []

    async def handle(item: int) -> None:
        handled.append(item)

    await ProducerConsumer(handle).run(source())

    assert sorted(handled) == list(range(5))


async def test_queue_and_consumer_limits_hold():
    active = max_active = 0

    async def handle(item: int) -> None:
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.001)
        active -= 1

    pipeline = ProducerConsumer(handle, consumer_count=3, queue_size=10)
    await pipeline.run(range(100))

    assert max_active == 3


async def test_failure_cancels_other_consumers():
    cancelled = 0

    async def handle(item: int) -> None:
        nonlocal cancelled
        if item == 0:
            raise ValueError(item)
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled += 1
            raise

    with pytest.raises(ExceptionGroup) as excinfo:
        async with asyncio.timeout(1):
            await ProducerConsumer(handle, consumer_count=3).run(range(20))

    assert excinfo.group_contains(ValueError)
    assert cancelled == 2


async def test_cancel_with_blocked_consumers_and_full_queue_exits():
    async def handle(item: int) -> None:
        await asyncio.Event().wait()

    pulled = 0

    def source():
        nonlocal pulled
        for item in range(100):
            pulled += 1
            yield item

    pipeline = ProducerConsumer(handle, consumer_count=3, queue_size=10)
    task = asyncio.create_task(pipeline.run(source()))
    await asyncio.sleep(0.01)
    # 3 held by blocked consumers, 10 queued, 1 waiting in put().
    assert pulled == 14

    task.cancel()
    async with asyncio.timeout(1):
        with pytest.raises(asyncio.CancelledError):
            await task
    others = asyncio.all_tasks() - {asyncio.current_task()}
    assert not others


@pytest.mark.parametrize("kwargs", [{"consumer_count": 0}, {"queue_size": 0}])
def test_rejects_non_positive_sizes(kwargs):
    async def handle(item: int) -> None:
        pass

    with pytest.raises(ValueError):
        ProducerConsumer(handle, **kwargs)
