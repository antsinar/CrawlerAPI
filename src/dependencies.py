from importlib import import_module
from types import ModuleType
from typing import Annotated, Callable, List, Optional
from urllib.parse import ParseResult, urlparse

import orjson
from fastapi import Depends, HTTPException, Request
from networkx import Graph, node_link_graph

from .constants import GRAPH_ROOT, HTTPS_SCHEME, Compressor, compressor_extensions


async def validate_url(request: Request) -> None:
    """Basic url validator; returns if url is valid
    :param url: url to validate
    :return: None
    """
    try:
        req = await request.json()
        result = urlparse(req["url"])
        all([result.scheme, result.netloc])
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid URL")


def get_crawled_urls(request: Request) -> List[str]:
    """Return list of crawled urls, found as compressed files in GRAPH_ROOT
    :return: List[str] (url netlocs)
    """
    return [
        graph.stem
        for graph in GRAPH_ROOT.iterdir()
        if graph.is_file()
        and graph.suffix == compressor_extensions[request.state.compressor.value]
    ]


def url_in_crawled(
    url: str, crawled_urls: Annotated[List[str], Depends(get_crawled_urls)]
) -> None:
    """Check if url is already crawled
    :param url: url to check
    :return: None
    """
    parsed: ParseResult = urlparse(url)
    if parsed.netloc not in crawled_urls:
        raise HTTPException(status_code=404, detail="Website not yet crawled")
    return


async def queued_url_in_crawled(
    request: Request, crawled_urls: Annotated[List[str], Depends(get_crawled_urls)]
):
    """Check if url is already queued for crawling
    :param url: url to check
    :return: None
    """
    req = await request.json()
    parsed: ParseResult = urlparse(req["url"])
    if parsed.netloc in crawled_urls:
        raise HTTPException(status_code=409, detail="Already Crawled")
    return


def extract_graph(
    url: str,
    compressor_module: ModuleType,
    extension: str,
    url_crawled: bool,
) -> Optional[Graph]:
    """Create and return networkx graph from a compressed file, if the requested ulr is already crawled
    :param url: url to extract graph from
    :param compressor_module: compressor module
    :param extension: compressed file extension
    :return: networkx graph
    """
    if not url_crawled:
        return
    parsed: ParseResult = urlparse(url)
    file_name = (GRAPH_ROOT / parsed.netloc).as_posix()
    with compressor_module.open(file_name + extension, "rb") as compressed:
        G = node_link_graph(orjson.loads(compressed.read()), edges="edges")
    return G


class GraphResolver:
    def __init__(self, url: str | None = None) -> None:
        self.url = url

    def __call__(self, compressor: Compressor, url_crawled: bool) -> Graph:
        compressor_module: ModuleType = import_module(compressor.value)
        G: Optional[Graph] = extract_graph(
            self.url,
            compressor_module=compressor_module,
            extension=compressor_extensions[compressor],
            url_crawled=url_crawled,
        )
        if not G:
            raise HTTPException(status_code=404, detail="Website not yet crawled")

        return G


def graph_resolvers(
    crawled_urls: Annotated[List[str], Depends(get_crawled_urls)],
) -> dict[str, GraphResolver]:
    """Return dictionary of graph dependency callables"""
    return {url: GraphResolver(HTTPS_SCHEME + url) for url in crawled_urls}


def get_resolver(
    url: str,
    resolvers: Annotated[dict[str, GraphResolver], Depends(graph_resolvers)],
) -> Callable[[Compressor, bool], Graph]:
    """Return graph dependency callable
    url parameter already exists at that point
    """
    try:
        return resolvers[urlparse(url).netloc]
    except KeyError:
        raise HTTPException(
            status_code=500, detail="Unexpected error: get_resolver dependency"
        )
