import asyncio
import logging
from contextlib import asynccontextmanager
from importlib import import_module
from os import environ
from types import ModuleType
from typing import AsyncGenerator, Generator, Optional
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import networkx as nx
import orjson
from httpx import AsyncClient, AsyncHTTPTransport, RequestError
from lxml import html

from .constants import GRAPH_ROOT, Compressor, compressor_extensions
from .models import AdjList, Node

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class Crawler:
    def __init__(
        self, client: AsyncClient, max_depth: int = 5, semaphore_size: int = 50
    ) -> None:
        self.client: AsyncClient = client
        self.max_depth: int = max_depth
        self.semaphore_size: int = semaphore_size
        self.robotparser: Optional[RobotFileParser] = None
        self.graph: nx.Graph = nx.Graph()

    async def parse_robotsfile(self) -> None:
        """Create a parser instance to check against while crawling"""
        robotparser = RobotFileParser()
        rbfile = await self.client.get("/robots.txt")
        robotparser.parse(rbfile.text.split("\n") if rbfile.status_code == 200 else "")
        self.robotparser = robotparser

    async def check_robots_compliance(self, url: str) -> bool:
        """Check if url is allowed by robots.txt
        :param url: url to check
        :return: bool
        """
        return self.robotparser.can_fetch("*", url)

    async def build_graph(self, start_url: str) -> None:
        """Function to run from the task queue to process a url and compress the graph
        :param start_url: url to start from
        """
        visited = set()
        semaphore = asyncio.Semaphore(self.semaphore_size)

        async def crawl(
            crawler: Crawler,
            url: str,
            depth: int,
        ) -> None:
            """Recursive function to crawl a website and build a graph
            :param depth: depth of recursion; how many calls shall be allowed
            """
            if depth > crawler.max_depth or url in visited:
                return

            p = urlparse(url).path
            logger.info(f"Crawling: {p}")
            visited.add(url)
            crawler.graph.add_node(url)

            try:
                async with semaphore:
                    response = await crawler.client.get(url)
                if response.status_code != 200:
                    logger.info(f"Non-200 response: {p}")
                    return
                if "text/html" not in response.headers["Content-Type"]:
                    logger.info(f"Not HTML: {p}")
                    return
                if not await crawler.check_robots_compliance(url):
                    logger.info(f"Blocked by robots.txt: {p}")
                    return

                tree = html.fromstring(response.text)

                for href in tree.cssselect("a[href]"):
                    full_url = urljoin(url, href.attrib["href"], allow_fragments=False)

                    if urlparse(full_url).netloc == urlparse(start_url).netloc:
                        crawler.graph.add_edge(url, full_url)
                        await crawl(crawler, full_url, depth + 1)

            except RequestError as e:
                logger.error(e)

        try:
            async with asyncio.TaskGroup() as tg:
                results = tg.create_task(crawl(self, start_url, 0))
        except* ValueError as IPError:
            logger.error("Terminating due to error", IPError)
        return

    async def compress_graph(
        self,
        file_name: str,
        compressor_module: ModuleType,
        extension: str,
    ) -> None:
        """Save graph to disk in compressed format"""
        if self.graph.number_of_nodes() <= 1:
            logger.info("Skipping compression, no graph nodes found")
            return
        file_name = (GRAPH_ROOT / file_name).as_posix()
        data = nx.node_link_data(self.graph, edges="edges")
        with compressor_module.open(file_name + extension, "wb") as f:
            f.write(orjson.dumps(data))


@asynccontextmanager
async def generate_client(
    base_url: Optional[str] = "",
) -> AsyncGenerator[AsyncClient, None]:
    """Configure an async http client for the crawler to use"""
    headers = {
        "User-Agent": "MapMakingCrawler/0.3.7",
        "Accept": "text/html,application/json,application/xml;q=0.9",
        "Keep-Alive": "500",
        "Connection": "keep-alive",
        "Accept-Encoding": "gzip, deflate, br",
    }
    in_production = environ.get("ENV", "development") == "production"
    transport = AsyncHTTPTransport(
        retries=3,
        verify=in_production,
        http2=True,
        http1=not in_production,
    )
    client = AsyncClient(
        base_url=base_url, transport=transport, headers=headers, follow_redirects=True
    )
    try:
        yield client
    except RequestError as e:
        logger.error(e)
    finally:
        await client.aclose()


async def process_url(url: str, compressor: Compressor = Compressor.GZIP) -> None:
    """Function to run from the task queue to process a url and compress the graph
    Contains all necessary steps to crawl a website and save a graph to disk in a
    compressed format
    :param url: base url to crawl
    :param compressor: compressor module to use
    :return: Future (in separate thread)
    """
    compressor_module = import_module(compressor.value)
    async with generate_client(url) as client:
        crawler = Crawler(client=client, max_depth=10, semaphore_size=30)
        await crawler.parse_robotsfile()
        logger.info("Crawling Website")
        await crawler.build_graph(url)
        logger.info("Compressing Graph")
        await crawler.compress_graph(
            urlparse(url).netloc,
            compressor_module,
            compressor_extensions[compressor],
        )


def generate_graph(G: nx.Graph) -> Generator[str, None, None]:
    """Return generator expression of serialized graph neighborhoods
    :param G: networkx graph, undirected
    :return: generator of serialized AdjList model
    """
    return (
        AdjList(
            source=Node(id=source),
            dest=[Node(id=key) for key in dest_dict],
        ).model_dump_json()
        for source, dest_dict in G.adjacency()
    )


def get_neighborhood(G: nx.Graph, node: Node) -> Optional[AdjList]:
    """Return the list of connected nodes to a given graph node instance, if any"""
    if node.id not in G.nodes:
        return
    neighborhood = G.neighbors(node.id)
    return AdjList(source=node, dest=[Node(id=n) for n in neighborhood])
