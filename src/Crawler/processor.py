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
    FULL = auto()
    AVAILABLE = auto()


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

    @property
    def state(self) -> State:
        match self.capacity:
            case 0:
                return State.FULL
            case _:
                return State.AVAILABLE

    @asynccontextmanager
    async def on_queue_push(self) -> AsyncGenerator[None, None]:
        try:
            yield
        finally:
            if self.state == State.AVAILABLE:
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

    def task_done(self, future) -> None:
        logger.info("Future finished")
        self.queue.task_done()
        self.capacity += 1
        if self.get_size() > 0:
            asyncio.get_running_loop().create_task(self.process_queue())

    async def push_url(self, url: str) -> None:
        """Pushes a url into the task queue"""
        async with self.on_queue_push():
            await self.queue.put(url)

    async def process_queue(self):
        """Iterate on the urls in the queue and process them in a separate thread
        The capacity parameter indicates how many urls can be processed in concurrently
        """
        self.capacity -= 1
        try:
            url = await self.queue.get()
            loop = asyncio.get_running_loop()
            task = loop.create_task(
                process_url(url, self.compressor, self.crawl_depth, self.request_limit)
            )
            task.add_done_callback(self.task_done)
        except Exception as e:
            logger.error(e)
        finally:
            pass

    async def get_parsed_urls(self):
        """
        Access these variables from the crawler instance
        request_counter
        error_counter
        TODO: Add status reporting mechanism for the crawler module
        """
        return {"OK": 100, "ERROR": 0}

    async def get_status(self):
        return {
            "state": self.state,
            "size": self.get_size(),
        }

    async def stop(self):
        """Graceful shutdown of the task queue and executor;
        Waits until all taskes inside the queue are executed
        """
        logger.info("Shutting down Task Queue")
        # TODO: cancel all running task
