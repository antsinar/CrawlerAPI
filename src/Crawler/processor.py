import asyncio
import logging
from contextlib import asynccontextmanager
from enum import StrEnum, auto
from typing import AsyncGenerator

from src.constants import Compressor, ConcurrentRequestLimit, CrawlDepth
from src.Crawler.lib import process_url

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class State(StrEnum):
    RUNNING = auto()
    IDLE = auto()


class TaskQueue:
    def __init__(
        self,
        compressor: Compressor,
        capacity: int = 1,
        crawl_depth=CrawlDepth.AVERAGE,
        request_limit=ConcurrentRequestLimit.AVERAGE,
    ):
        self.queue = asyncio.Queue()
        self.capacity: int = capacity
        self.compressor: Compressor = compressor
        self.crawl_depth = crawl_depth
        self.request_limit = request_limit
        self.state: State = State.IDLE

    @asynccontextmanager
    async def on_queue_push(self) -> AsyncGenerator[None, None]:
        yield
        if self.capacity > 0 and self.state == State.IDLE:
            await self.process_queue()

    @asynccontextmanager
    async def capacity_semaphore(self) -> AsyncGenerator[None, None]:
        self.capacity -= 1
        try:
            yield
        except Exception:
            pass
        finally:
            self.capacity += 1

    def get_size(self) -> int:
        return self.queue.qsize()

    def get_capacity(self) -> int:
        return self.capacity

    async def push_url(self, url: str) -> None:
        """Pushes a url into the task queue"""
        async with self.on_queue_push():
            await self.queue.put(url)

    async def process_queue(self):
        """Iterate on the urls in the queue and process them in a separate thread
        The capacity parameter indicates how many urls can be processed in concurrently
        FIXME: Does not prevent an out of bounds call
        Note:
            Since I am not awaiting the task created by the loop.create_task() call, the capacity semaphore
            is released before the task is done; after exiting the block.
            This might be the reason the capacity is not respected
        """
        async with self.capacity_semaphore():
            self.state = State.RUNNING
            url = await self.queue.get()
            loop = asyncio.get_running_loop()
            loop.create_task(
                process_url(url, self.compressor, self.crawl_depth, self.request_limit)
            )
            self.queue.task_done()

        if self.capacity > 0:
            await self.process_queue()

        self.state = State.IDLE

    async def get_parsed_urls(self):
        """
        Access these variables from the crawler instance
        request_counter
        error_counter
        """
        return {"OK": 100, "ERROR": 0}

    async def get_status(self):
        return {
            "state": self.state,
            "progress": await self.get_parsed_urls()
            if self.state == State.RUNNING
            else None,
            "capacity": self.capacity,
        }

    async def stop(self):
        """Graceful shutdown of the task queue and executor;
        Waits until all taskes inside the queue are executed
        """
        logger.info("Shutting down Task Queue & Executor")
        await self.queue.join()
