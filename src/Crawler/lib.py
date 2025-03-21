import asyncio
import logging
from contextlib import asynccontextmanager
from importlib import import_module
from types import ModuleType
from typing import AsyncGenerator, List, Optional
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import chardet
import networkx as nx
import orjson
from httpx import AsyncClient, AsyncHTTPTransport, HTTPStatusError, RequestError
from lxml import html
from lxml.cssselect import CSSSelector
from lxml.etree import ParseError

from src.constants import (
    GRAPH_ROOT,
    Compressor,
    ConcurrentRequestLimit,
    CrawlDepth,
    compressor_extensions,
)
from src.Graph.models import AdjList, Node

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
        self.exclusion_list: List[str] = [".pdf", ".xml", ".jpg", ".png"]

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

    async def pre_crawl_setup(self, start_url: str) -> bool:
        """Returns a ready for crawl flag
        The result can be false, not ready for crawl, if the website returns an error
        http status code.
        Otherwise moodify the headers of the client pool if its perfoming the upcoming
        requests over http/2
        """
        test_connection_response = await self.client.head(start_url)

        try:
            test_connection_response.raise_for_status()
        except HTTPStatusError:
            logger.info("Crawling not permitted on this website")
            return False

        if test_connection_response.extensions["http_version"] == b"HTTP/2":
            del self.client.headers["Keep-Alive"]
            del self.client.headers["Connection"]
            logger.info("Set up headers for http/2")

        logger.info(
            f"Crawling initialized from client @ {test_connection_response.extensions['network_stream'].get_extra_info('server_addr')}"
        )
        return True

    def check_against_exclusion_list(self, path: str) -> bool:
        """Return True if the path matches a pattern inside the crawler's exclusion list"""
        for item in self.exclusion_list:
            if item in path:
                return True
        return False

    async def build_graph(self, start_url: str) -> None:
        """Function to run from the task queue to process a url and compress the graph
        :param start_url: url to start from
        """
        visited = set()
        semaphore = asyncio.Semaphore(self.semaphore_size)

        if not await self.pre_crawl_setup(start_url):
            return

        anchor_selector = CSSSelector("a[href]")

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

            p = urlparse(url, allow_fragments=False).path
            logger.info(f"Crawling: {p}")
            visited.add(url)
            crawler.graph.add_node(url)

            # TODO: check against exclusion list before the GET request -- Faster overall than a head request
            if self.check_against_exclusion_list(p):
                return

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
                try:
                    tree = html.document_fromstring(response.text)
                except ParseError as e:
                    logger.error(e)
                    return

                for href in anchor_selector(tree):
                    full_url = urljoin(url, href.attrib["href"], allow_fragments=False)
                    next_url = urlparse(full_url, allow_fragments=False)
                    if "cdn-cgi" in next_url.path:
                        return
                    if next_url.netloc == urlparse(start_url).netloc:
                        crawler.graph.add_edge(url, full_url)
                        await crawl(crawler, full_url, depth + 1)

            except RequestError as e:
                logger.error(e)

        try:
            async with asyncio.TaskGroup() as tg:
                tg.create_task(crawl(self, start_url, 0))
        except* ValueError as IPErrorGroup:
            logger.error(
                "Terminating due to error",
                *[str(e)[:100] for e in IPErrorGroup.exceptions],
            )
        except* KeyError as HeaderMissingErrorGroup:
            logger.error(
                "Terminating due to error",
                *[str(e)[:50] for e in HeaderMissingErrorGroup.exceptions],
            )
        except* ParseError as ParserErrorGroup:
            logger.error(
                "Terminating due to error",
                *[str(e)[:100] for e in ParserErrorGroup.exceptions],
            )
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
        "User-Agent": "MapMakingCrawler/0.4.2",
        "Accept": "text/html,application/json,application/xml;q=0.9",
        "Keep-Alive": "500",
        "Connection": "keep-alive",
        "Accept-Encoding": "gzip, deflate, br",
        "Accept-Language": "en, el-GR;q=0.9",
    }
    transport = AsyncHTTPTransport(retries=3, http2=True)
    client = AsyncClient(
        base_url=base_url,
        transport=transport,
        headers=headers,
        follow_redirects=True,
        default_encoding=lambda content: chardet.detect(content).get("encoding"),
    )
    try:
        yield client
    except RequestError as e:
        logger.error(e)
    finally:
        await client.aclose()


async def process_url(
    url: str,
    compressor: Compressor,
    crawl_depth: CrawlDepth,
    request_limit: ConcurrentRequestLimit,
) -> None:
    """Function to run from the task queue to process a url and compress the graph
    Contains all necessary steps to crawl a website and save a graph to disk in a
    compressed format
    :param url: base url to crawl
    :param compressor: compressor module to use
    :return: Future (in separate thread)
    """
    compressor_module = import_module(compressor.value)
    async with generate_client(url) as client:
        crawler = Crawler(
            client=client,
            max_depth=crawl_depth.value,
            semaphore_size=request_limit.value,
        )
        await crawler.parse_robotsfile()
        logger.info("Crawling Website")
        await crawler.build_graph(url)
        logger.info("Compressing Graph")
        await crawler.compress_graph(
            urlparse(url).netloc,
            compressor_module,
            compressor_extensions[compressor],
        )


def get_neighborhood(G: nx.Graph, node: Node) -> Optional[AdjList]:
    """Return the list of connected nodes to a given graph node instance, if any"""
    if node.id not in G.nodes:
        return
    neighborhood = G.neighbors(node.id)
    return AdjList(source=node, dest=[Node(id=n) for n in neighborhood])
