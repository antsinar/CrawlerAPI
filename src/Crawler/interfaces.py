from types import ModuleType
from typing import Protocol


class ICrawler(Protocol):
    async def parse_robotsfile(self) -> None: ...

    async def build_graph(self, start_url: str) -> None: ...

    async def compress_graph(
        self,
        file_name: str,
        compressor_module: ModuleType,
        extension: str,
    ) -> None: ...


class ITaskQueue(Protocol):
    def get_capacity(self) -> int: ...

    def get_size(self) -> int: ...

    async def push_url(self, url: str) -> None:
        """Pushes a url into the task queue"""
        ...

    async def process_queue(self):
        """Iterate on the urls in the queue and process them in a separate thread
        The capacity parameter indicates how many urls can be processed in concurrently
        FIXME: Does not prevent an out of bounds call
        Note:
            Since I am not awaiting the task created by the loop.create_task() call, the capacity semaphore
            is released before the task is done; after exiting the block.
            This might be the reason the capacity is not respected
        """
        ...

    async def get_parsed_urls(self):
        """
        Access these variables from the crawler instance
        request_counter
        error_counter
        """
        ...

    async def get_status(self): ...

    async def stop(self):
        """Graceful shutdown of the task queue and executor;
        Waits until all taskes inside the queue are executed
        """
        ...
