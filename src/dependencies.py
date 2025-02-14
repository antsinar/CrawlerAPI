from importlib import import_module
from types import ModuleType
from typing import Annotated, Callable, List, Optional
from urllib.parse import ParseResult, urlparse

import orjson
from fastapi import Depends, HTTPException, Request
from networkx import Graph, node_link_graph

from .constants import GRAPH_ROOT, HTTPS_SCHEME, Compressor, compressor_extensions
from .models import Course


async def validate_url(request: Request) -> None:
    """Basic url validator; returns if url is valid
    :param request: Request object from FastAPI; contains QueueUrl object from post request
    returns if the url is valid, else raises HTTPException
    """
    try:
        req = await request.json()
        result = urlparse(req["url"])
        all([result.scheme, result.netloc])
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid URL")


def get_crawled_urls(request: Request) -> List[str]:
    """Return list of crawled urls, found as compressed files in GRAPH_ROOT
    :param request: Request object from FastAPI; contains Compressor object
    :return: url netlocs as a list
    """
    return [
        graph.stem
        for graph in GRAPH_ROOT.iterdir()
        if graph.is_file()
        and graph.suffix == compressor_extensions[request.app.state.compressor.value]
    ]


def url_in_crawled(
    url: str, crawled_urls: Annotated[List[str], Depends(get_crawled_urls)]
) -> None:
    """Check if url is already crawled
    :param url: url to check
    :param crawled_urls: list of already crawled urls, as a fastapi dependency
    returns if url is in crawled_urls, else raises HTTPException
    """
    parsed: ParseResult = urlparse(url)
    if parsed.netloc not in crawled_urls:
        raise HTTPException(status_code=404, detail="Website not yet crawled")
    return


async def url_in_crawled_from_object(
    request: Request, crawled_urls: Annotated[List[str], Depends(get_crawled_urls)]
):
    """Check if a QueueUrl object is already crawled
    :param request: Request object from FastAPI; contains QueueUrl object from post request
    :param crawled_urls: list of already crawled urls, as a fastapi dependency
    returns if url is in crawled_urls, else raises HTTPException
    """
    req = await request.json()
    parsed: ParseResult = urlparse(req["url"])
    if parsed.netloc not in crawled_urls:
        raise HTTPException(status_code=404, detail="Website not yet crawled")
    return


async def url_not_in_crawled_from_object(
    request: Request, crawled_urls: Annotated[List[str], Depends(get_crawled_urls)]
):
    """Check if a QueueUrl object is not already crawled
    :param request: Request object from FastAPI; contains QueueUrl object from post request
    :param crawled_urls: list of already crawled urls, as a fastapi dependency
    returns if url is not in crawled_urls, else raises HTTPException
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
    :param url_crawled: boolean, is the url already crawled?
    returns a networkx graph, if the url is already crawled, else None
    """
    if not url_crawled:
        return
    parsed: ParseResult = urlparse(url)
    file_name = (GRAPH_ROOT / parsed.netloc).as_posix()
    with compressor_module.open(file_name + extension, "rb") as compressed:
        contents = compressed.read()
        G = node_link_graph(orjson.loads(contents), edges="edges")
    return G


class GraphResolver:
    def __init__(self, url: str | None = None) -> None:
        self.url = url

    def __call__(self, compressor: Compressor, url_crawled: bool) -> Graph:
        """Extracts a networkx graph object from a compressed file for a given
        url and compressor module.
        :param compressor: compressor module
        :param url_crawled: boolean, is the url already crawled?
        returns a networkx graph, if the url is already crawled, else raise HTTPException
        """
        compressor_module: ModuleType = import_module(compressor.value)
        G: Optional[Graph] = extract_graph(
            self.url,
            compressor_module=compressor_module,
            extension=compressor_extensions[compressor.value],
            url_crawled=url_crawled,
        )
        if not G:
            raise HTTPException(status_code=404, detail="Website not yet crawled")

        return G


def graph_resolvers(
    crawled_urls: Annotated[List[str], Depends(get_crawled_urls)],
) -> dict[str, GraphResolver]:
    """Return dictionary of GraphResolver callables, initiated for every crawled url"""
    return {url: GraphResolver(HTTPS_SCHEME + url) for url in crawled_urls}


def get_resolver(
    url: str,
    resolvers: Annotated[dict[str, GraphResolver], Depends(graph_resolvers)],
) -> Callable[[Compressor, bool], Graph]:
    """Returns the corresponding GraphResolver instance for the given url
    :param url: url to get resolver for, usually already validated at that point
    :param resolvers: dictionary of GraphResolver callables
    In the chance the url does not exist, raise 500 HTTPException
    """
    try:
        return resolvers[urlparse(url).netloc]
    except KeyError:
        raise HTTPException(
            status_code=500, detail="Unexpected error: get_resolver dependency"
        )


async def get_resolver_from_object(
    request: Request,
    resolvers: Annotated[dict[str, GraphResolver], Depends(graph_resolvers)],
) -> Callable[[Compressor, bool], Graph]:
    res = await request.json()
    return resolvers[urlparse(res["url"]).netloc]


async def resolve_course_url(request: Request, uid: str) -> str:
    """Search the running courses for given course uid and return the url, otherwise raise HTTPExceprion"""
    if uid not in request.app.state.active_courses.keys():
        raise HTTPException(
            status_code=404, detail="ID does not correspond to an active course"
        )
    return request.app.state.active_courses[uid]


async def resolve_graph_from_course(
    request: Request,
    uid: str,
    course_url: Annotated[Course, Depends(resolve_course_url)],
    resolvers: Annotated[dict[str, GraphResolver], Depends(graph_resolvers)],
) -> Callable[[Compressor, bool], Graph]:
    """Determine a course from its uid and return the corresponding graph resolver object"""
    return resolvers[urlparse(course_url).netloc]
