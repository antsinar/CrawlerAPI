import asyncio
import logging
from concurrent.futures import ProcessPoolExecutor
from functools import partial
from importlib import import_module
from pathlib import Path
from typing import Dict, List

import orjson

from .constants import GRAPH_ROOT, Compressor, compressor_extensions
from .models import GraphInfo

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class GraphManager:
    def __init__(self, compressor: Compressor, processes: int = 2) -> None:
        self.compressor = compressor
        self.pool = ProcessPoolExecutor(max_workers=processes)
        self.graphs: List[Path] = None
        self.graph_info: dict[str, GraphInfo] = None
        self.available = True

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

    async def graph_cleanup(self) -> None:
        """Delete invalid graphs from file system"""
        last_modified = GRAPH_ROOT.stat().st_mtime
        loop = asyncio.get_running_loop()
        logger.info("Starting Graph Cleanup background task")
        while self.available:
            if last_modified == GRAPH_ROOT.stat().st_mtime:
                continue
            logger.info("Detected change inside the graph directory")
            self._collect_graphs()
            map_fn = partial(self.pool.map, self._sweep_dirty_graph, self.graphs)
            res = await loop.run_in_executor(self.pool, map_fn)
            last_modified = GRAPH_ROOT.stat().st_mtime


class GraphInfoUpdater(GraphManager):
    def __init__(self, compressor: Compressor, processes: int = 4):
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
            logger.info(f"Updated graph info for {graph.stem}")

    async def update_info(self) -> None:
        """Update graph info in app state"""
        self._collect_graphs()
        [self.pool.submit(self._update_graph_info(graph)) for graph in self.graphs]

    async def watch_graphs(self) -> None:
        """Watch graph directory for changes and update graphs"""
        logger.info("Starting Graph Watch background task")
        last_modified = GRAPH_ROOT.stat().st_mtime
        loop = asyncio.get_running_loop()
        while self.available:
            if last_modified == GRAPH_ROOT.stat().st_mtime:
                continue
            logger.info("Detected change inside the graph directory")
            asyncio.gather(asyncio.create_task(self.update_info()))
            last_modified = GRAPH_ROOT.stat().st_mtime
