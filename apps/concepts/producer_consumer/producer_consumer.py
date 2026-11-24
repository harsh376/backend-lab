import asyncio
from collections.abc import AsyncIterable, Awaitable, Callable, Iterable


class ProducerConsumer[T]:
    """Feed items through a bounded queue to a fixed pool of consumers.

    The producer blocks while the queue is full, so it never runs more than
    `queue_size` items ahead of the consumers. If `handle` raises, or `run` is
    cancelled, every task is cancelled and awaited before `run` exits; errors
    surface as an ExceptionGroup.

    Any exception from `handle` aborts the whole run, so `handle` should catch
    errors that only affect one item and raise only when every item should stop.
    """

    def __init__(
        self,
        handle: Callable[[T], Awaitable[None]],
        consumer_count: int = 3,
        queue_size: int = 10,
    ):
        if consumer_count < 1:
            raise ValueError("consumer_count must be >= 1")
        if queue_size < 1:
            # asyncio treats maxsize <= 0 as unbounded.
            raise ValueError("queue_size must be >= 1")
        self.handle = handle
        self.consumer_count = consumer_count
        self.queue_size = queue_size

    async def run(self, items: Iterable[T] | AsyncIterable[T]) -> None:
        queue: asyncio.Queue[T] = asyncio.Queue(maxsize=self.queue_size)
        async with asyncio.TaskGroup() as tg:
            consumers = [
                tg.create_task(self.consume(queue)) for _ in range(self.consumer_count)
            ]
            await self.produce(queue, items)
            await queue.join()
            # Consumers loop forever; once the queue drains they're idle in get().
            for consumer in consumers:
                consumer.cancel()

    async def produce(
        self, queue: asyncio.Queue[T], items: Iterable[T] | AsyncIterable[T]
    ) -> None:
        # put() blocks while the queue is full, so the source is only read as
        # fast as the consumers drain it.
        if isinstance(items, AsyncIterable):
            async for item in items:
                await queue.put(item)
        else:
            for item in items:
                await queue.put(item)

    async def consume(self, queue: asyncio.Queue[T]) -> None:
        while True:
            item = await queue.get()
            try:
                await self.handle(item)
            finally:
                queue.task_done()
