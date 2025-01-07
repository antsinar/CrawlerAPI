import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from importlib import import_module
from pathlib import Path
from typing import Callable, Dict, List, Optional

import orjson

from .constants import GRAPH_ROOT, Compressor, compressor_extensions
from .models import GraphInfo

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class GraphManager:
    def __init__(self, compressor: Compressor, processes: Optional[int] = None) -> None:
        self.compressor = compressor
        self.pool = ThreadPoolExecutor(max_workers=processes)
        self.graphs: List[Path] = None
        self.graph_info: dict[str, GraphInfo] = None
        self.available = True
        self.parsed: set[Path] = set()

    def _collect_graphs(self) -> None:
        self.graphs = [
            graph
            for graph in GRAPH_ROOT.iterdir()
            if graph.is_file()
            and graph.suffix == compressor_extensions[self.compressor.value]
        ]

    async def stop(self) -> None:
        """Force shutdown of the executor"""
        logger.info("Shutting down Manager Executor")
        self.available = False
        self.pool.shutdown()


class GraphCleaner(GraphManager):
    def _sweep_dirty_graph(self, graph: Path) -> None:
        """Detect graphs with invalid json data"""
        compressor_module = import_module(self.compressor.value)
        with compressor_module.open(graph, "rb") as f:
            try:
                orjson.loads(f.read())
            except orjson.JSONDecodeError:
                graph.unlink()

    def sweep(self, force: bool = False):
        self._collect_graphs()
        if not force:
            remaining = [graph for graph in self.graphs if graph not in self.parsed]
        else:
            remaining = self.graphs
        for graph, fn in zip(
            remaining, self.pool.map(self._sweep_dirty_graph, remaining)
        ):
            self.parsed.add(graph)
            logger.info(f"Examining {graph.name}")
        logger.info("Graph sweep complete")


class GraphInfoUpdater(GraphManager):
    def __init__(self, compressor: Compressor, processes: Optional[int] = None):
        super().__init__(compressor, processes)
        self.graph_info: Dict[str, GraphInfo] = {}

    def _update_graph_info(self, graph: Path) -> None:
        """Resolve graph information"""
        compressor_module = import_module(self.compressor.value)
        with compressor_module.open(graph, "rb") as f:
            data = orjson.loads(f.read())
            self.graph_info[graph.stem] = GraphInfo(
                num_nodes=len(data["nodes"]), num_edges=len(data["edges"])
            )

    def update_info(self, force: bool = False) -> None:
        """Update graph info in app state"""
        self._collect_graphs()
        if not force:
            remaining = [graph for graph in self.graphs if graph not in self.parsed]
        else:
            remaining = self.graphs
        for graph, fn in zip(
            remaining, self.pool.map(self._update_graph_info, remaining)
        ):
            self.parsed.add(graph)
            logger.info(f"Updated graph info for {graph.stem}")
        logger.info("Graph update complete")


class GraphWatcher(GraphManager):
    async def run_scheduled_functions(
        self, loop: asyncio.BaseEventLoop, functions: List[Callable[[None], None]]
    ):
        [await loop.run_in_executor(self.pool, fn) for fn in functions]

    async def watch_graphs(
        self, cleaner: GraphCleaner, updater: GraphInfoUpdater
    ) -> None:
        """Watch graph directory for changes and update graphs"""
        logger.info("Starting Graph Watch background task")
        last_modified = GRAPH_ROOT.stat().st_mtime
        loop = asyncio.get_event_loop()
        while self.available:
            if last_modified == GRAPH_ROOT.stat().st_mtime:
                await asyncio.sleep(1)
                continue
            logger.info("Detected change inside the graph directory")
            async with asyncio.TaskGroup() as tg:
                tg.create_task(
                    self.run_scheduled_functions(
                        loop, [cleaner.sweep, updater.update_info]
                    )
                )
            last_modified = GRAPH_ROOT.stat().st_mtime
