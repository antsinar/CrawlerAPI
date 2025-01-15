import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from functools import partial

from .constants import Compressor
from .lib import process_url

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TaskQueue:
    def __init__(self, compressor: Compressor, capacity: int = 1):
        self.queue = asyncio.Queue()
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.is_available: bool = True
        self.capacity: int = capacity
        self.compressor: Compressor = compressor

    def get_size(self) -> int:
        return self.queue.qsize()

    async def push_url(self, url: str) -> None:
        """Pushes a url into the task queue"""
        await self.queue.put(url)

    async def process_queue(self):
        """Iterate on the urls in the queue and process them in a separate thread
        The capacity parameter indicates how many urls can be processed in concurrently
        """
        while self.is_available:
            if self.capacity < 1:
                logger.info("Waiting for empty slot in Executor")
                # await asyncio.sleep(1)
                continue
            url = await self.queue.get()
            self.capacity -= 1
            loop = asyncio.get_running_loop()
            process_fn = partial(self._process_url, url)
            res = await loop.run_in_executor(self.pool, process_fn)
            self.queue.task_done()
            self.capacity += 1

    def _process_url(self, url: str):
        """Runs the processing function"""
        asyncio.run(process_url(url, self.compressor))

    async def stop(self):
        """Graceful shutdown of the task queue and executor;
        Waits until all taskes inside the queue are executed
        """
        logger.info("Shutting down Task Queue & Executor")
        try:
            self.is_available = False
            self.pool.shutdown(wait=True)
        except KeyboardInterrupt:
            exit(1)
