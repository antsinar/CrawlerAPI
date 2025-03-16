from importlib import import_module
from json import JSONDecodeError
from types import ModuleType
from typing import Annotated, Callable, List, Optional
from urllib.parse import ParseResult, urlparse

import orjson
from fastapi import Depends, HTTPException, Request
from networkx import Graph, node_link_graph

from .constants import (
    GRAPH_ROOT,
    HTTP_SCHEME,
    HTTPS_SCHEME,
    Compressor,
    compressor_extensions,
)


async def validate_url(request: Request) -> None:
    """
    Basic url validation; Returns if url passed in the request body is valid

    Args:
        request: Request object from FastAPI

    Raises:
        HTTPException: Url is not present in request body
        HTTPException: Url validation by urlparse failed to detect necessary attributes
    """
    try:
        req = await request.json()
    except JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    result = urlparse(req.get("url", None))
    if not result.scheme:
        raise HTTPException(status_code=400, detail="Url not present in request body")
    try:
        all([result.scheme, result.netloc])
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid URL")


async def get_crawled_urls(request: Request) -> List[str]:
    """
    Returns list of already crawled urls

    Args:
        request (Request): Request object from FastAPI

    Returns:
        List[str]: List of already crawled urls present in the storage medium
    """
    compressor = request.app.state.compressor.value
    return [
        graph.stem
        for graph in GRAPH_ROOT.iterdir()
        if graph.is_file() and graph.suffix == compressor_extensions[compressor]
    ]


async def url_in_crawled(
    url: str, crawled_urls: Annotated[List[str], Depends(get_crawled_urls)]
) -> None:
    """
    Checks if a url, passed as a url query parameter, is already crawled

    Args:
        url (str): A url string, including scheme and encoded in utf-8
        crawled_urls ([List[str]): The list of already crawled urls that runs as a fastapi dependency

    Raises:
        HTTPException: Website not yet crawled
    """
    parsed: ParseResult = urlparse(url)
    if parsed.netloc not in crawled_urls:
        raise HTTPException(status_code=404, detail="Website not yet crawled")
    return


async def url_in_crawled_from_object(
    request: Request, crawled_urls: Annotated[List[str], Depends(get_crawled_urls)]
) -> None:
    """
    Check if a url passed in the request body is already crawled

    Args:
        request (Request): Request object from FastAPI
        crawled_urls ([List[str]): The list of already crawled urls that runs as a fastapi dependency

    Returns:
        None: Returns if url is already crawled

    Raises:
        HTTPException: Url is not present in request body
        HTTPException: Website not yet crawled
    """
    try:
        req = await request.json()
    except JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    url = req.get("url", None)
    if not url:
        raise HTTPException(status_code=400, detail="Url not present in request body")
    parsed: ParseResult = urlparse(HTTP_SCHEME + url)
    if not parsed.scheme:
        raise HTTPException(status_code=400, detail="Wrong url format")
    if parsed.netloc not in crawled_urls:
        raise HTTPException(status_code=404, detail="Website not yet crawled")
    return


async def url_not_in_crawled_from_object(
    request: Request, crawled_urls: Annotated[List[str], Depends(get_crawled_urls)]
) -> None:
    """
    Check if a url passed in the request body is already crawled

    Args:
        request (Request): Request object from FastAPI
        crawled_urls ([List[str]): The list of already crawled urls that runs as a fastapi dependency

    Returns:
        None: Returns if url is not already crawled

    Raises:
        HTTPException: Url is not present in request body
        HTTPException: Website is already crawled
    """
    try:
        req = await request.json()
    except JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    url = req.get("url", None)
    if not url:
        raise HTTPException(status_code=400, detail="Url not present in request body")
    parsed: ParseResult = urlparse(HTTP_SCHEME + url)
    if not parsed.scheme:
        raise HTTPException(status_code=400, detail="Wrong url format")
    if parsed.netloc in crawled_urls:
        raise HTTPException(status_code=404, detail="Website not yet crawled")
    return


def extract_graph(
    url: str,
    compressor_module: ModuleType,
    extension: str,
    url_crawled: bool,
) -> Optional[Graph]:
    """
    Extracts a networkx graph object from a compressed file for a given
    url and compressor module.

    Args:
        url (str): url used to detect graph in storage
        compressor_module (ModuleType): compressor module used application wide
        extension (str): compressed file extension, matches compressor module
        url_crawled (bool): boolean, is the url already crawled?

    Returns:
        networkx.Graph:
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
    """
    Class to match a url to a networkx graph

    Args:
        url (str): url to extract graph from
    """

    def __init__(self, url: str | None = None) -> None:
        self.url = url

    def __call__(self, compressor: Compressor, url_crawled: bool = True) -> Graph:
        """
        When the object is called, extract a networkx graph object from a compressed
        file for a given url and a compressor module.

        Args:
            compressor (Compressor): Compressor Enum type
            url_crawled (bool): boolean, is the url already crawled?

        Raises:
            HTTPException: Website not yet crawled

        Returns:
            networkx.Graph: Graph assotiated with the url
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


async def graph_resolvers(
    crawled_urls: Annotated[List[str], Depends(get_crawled_urls)],
) -> dict[str, GraphResolver]:
    """
    Return dictionary of GraphResolver callables, initiated for every crawled url

    Args:
        crawled_urls (List[str]): List of already crawled urls

    Returns:
        dict[str, GraphResolver]: Dictionary of pre-computed GraphResolver callables
    """
    return {url: GraphResolver(HTTPS_SCHEME + url) for url in crawled_urls}


async def get_resolver(
    url: str,
    resolvers: Annotated[dict[str, GraphResolver], Depends(graph_resolvers)],
) -> Callable[[Compressor, bool], Graph]:
    """
    Returns the corresponding GraphResolver instance for the given url

    Args:
        url (str): url to extract graph from
        resolvers (Dict[str, GraphResolver]): Dictionary of pre-computed GraphResolver callables

    Raises:
        HTTPException: Unable to resolve url from pre-computed dictionary

    Returns:
        Callable[[Compressor, bool], Graph]: GraphResolver callable
    """
    try:
        return resolvers[urlparse(url).netloc]
    except KeyError:
        raise HTTPException(
            status_code=400, detail="Unexpected error: Unable to resolve url"
        )


async def get_resolver_from_object(
    request: Request,
    resolvers: Annotated[dict[str, GraphResolver], Depends(graph_resolvers)],
) -> Callable[[Compressor, bool], Graph]:
    """
    Returns the corresponding GraphResolver instance for the given url passed inside the request body

    Args:
        request (Request): Request object from FastAPI
        resolvers (Dict[str, GraphResolver]): Dictionary of pre-computed GraphResolver callables

    Raises:
        HTTPException: Unable to resolve url from pre-computed dictionary

    Returns:
        Callable[[Compressor, bool], Graph]: GraphResolver callable
    """
    try:
        res = await request.json()
    except JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    url = res.get("url", None)
    if not url:
        raise HTTPException(status_code=400, detail="Url not present in request body")
    resolver = resolvers.get(urlparse(HTTP_SCHEME + url).netloc, None)
    if not resolver:
        raise HTTPException(
            status_code=400, detail="Unexpected error: Unable to resolve url"
        )
    return resolver


async def resolve_course_url(request: Request, uid: str) -> str:
    """
    Search the running courses for given course uid and return the url

    Args:
        request (Request): Request object from FastAPI
        uid (str): ID of the course

    Raises:
        HTTPException: ID does not correspond to an active course

    Returns:
        str: url of the active course
    """
    if uid not in request.app.state.active_courses.keys():
        raise HTTPException(
            status_code=404, detail="ID does not correspond to an active course"
        )
    return request.app.state.active_courses[uid]


async def resolve_course_url_object(request: Request) -> str:
    """
    Search the running courses for given course uid given inside the request body and return the url

    Args:
        request (Request): Request object from FastAPI

    Raises:
        HTTPException: ID does not correspond to an active course

    Returns:
        str: url of the active course
    """
    try:
        res = await request.json()
    except JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    uid = res.get("uid", None)
    if not uid:
        raise HTTPException(status_code=400, detail="Uid not present in request body")
    if uid not in request.app.state.active_courses.keys():
        raise HTTPException(
            status_code=404, detail="ID does not correspond to an active course"
        )
    return request.app.state.active_courses[uid]


async def resolve_graph_from_course(
    request: Request,
    uid: str,
    course_url: Annotated[str, Depends(resolve_course_url)],
    resolvers: Annotated[dict[str, GraphResolver], Depends(graph_resolvers)],
) -> Callable[[Compressor, bool], Graph]:
    """
    Determine a course from its uid and return the corresponding graph resolver object

    Args:
        request (Request): Request object from FastAPI
        uid (str): ID of the course
        course_url (str): Url assotiated with the course
        resolvers dict[str, GraphResolver]: Dictionary of pre-computed GraphResolver callables

    Raises:
        HTTPException: Course url not found in pre-computed dictionary

    Returns:
        Callable[[Compressor, bool], Graph]: GraphResolver callable
    """
    try:
        return resolvers[urlparse(HTTPS_SCHEME + course_url).netloc]
    except KeyError as e:
        raise HTTPException(status_code=400, detail=str(e))


async def resolve_graph_from_course_object(
    request: Request,
    course_url: Annotated[str, Depends(resolve_course_url_object)],
    resolvers: Annotated[dict[str, GraphResolver], Depends(graph_resolvers)],
) -> Callable[[Compressor, bool], Graph]:
    """
    Determine a course from its uid given inside the request body and return the
    corresponding graph resolver object

    Args:
        request (Request): Request object from FastAPI
        course_url (str): Url assotiated with the course
        resolvers dict[str, GraphResolver]: Dictionary of pre-computed GraphResolver callables

    Raises:
        HTTPException: Course url not found in pre-computed dictionary

    Returns:
        Callable[[Compressor, bool], Graph]: GraphResolver callable
    """
    try:
        return resolvers[urlparse(HTTP_SCHEME + course_url).netloc]
    except KeyError as e:
        raise HTTPException(status_code=400, detail=str(e))
