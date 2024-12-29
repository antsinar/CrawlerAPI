import asyncio
from contextlib import asynccontextmanager
from os import environ
from typing import Annotated, Callable, List

import networkx as nx
from dotenv import find_dotenv, load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse

from .constants import GRAPH_ROOT, Compressor
from .dependencies import (
    get_crawled_urls,
    get_resolver,
    queued_url_in_crawled,
    url_in_crawled,
    validate_url,
)
from .lib import generate_graph, get_neighborhood
from .models import AdjList, GraphInfo, Node, QueueUrl
from .processor import TaskQueue


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        load_dotenv(find_dotenv(".env"))
        environment = environ.get("ENV", "development")
        GRAPH_ROOT.mkdir(exist_ok=True)
        task_queue = TaskQueue(capacity=1)
        app.state.task_queue = task_queue
        app.state.compressor = Compressor.GZIP
        app.state.environment = environment
        processor = asyncio.create_task(task_queue.process_queue())
        yield
    except Exception as e:
        pass
    finally:
        await task_queue.stop()


app = FastAPI(
    lifespan=lifespan,
    openapi_url="/openapi.json"
    if environ.get("ENV", "development") != "production"
    else None,
)
app.add_middleware(GZipMiddleware, minimum_size=3000, compresslevel=7)


@app.middleware("http")
async def pass_state_to_request(request: Request, call_next):
    request.state.compressor = app.state.compressor
    request.state.environment = app.state.environment
    if request.method == "POST" and request.url.path in [
        "/queue-website/",
    ]:
        request.state.task_queue = app.state.task_queue
    return await call_next(request)


@app.middleware("http")
async def redirect_to_maintenance(request: Request, call_next):
    if environ.get("MAINTENANCE", "False") == "False":
        return await call_next(request)
    raise HTTPException(
        status_code=503,
        detail="Server Unavailable due to maintenance",
        headers={"X-Server-Mode": "Maintenance Mode"},
    )


@app.get("/", include_in_schema=False)
async def root(request: Request):
    """Redirect to docs, if not in production"""
    return (
        RedirectResponse(url="/docs")
        if request.state.environment != "production"
        else {RedirectResponse(url="/graphs/all")}
    )


@app.get("/graphs/all")
async def graphs(crawled_urls: Annotated[List[str], Depends(get_crawled_urls)]):
    """Return already crawled website graphs"""
    return {
        "crawled_urls": crawled_urls,
    }


@app.get("/graphs/", response_model=GraphInfo)
async def graph_info(
    request: Request,
    url: str,
    url_crawled: Annotated[None, Depends(url_in_crawled)],
    resolver: Annotated[Callable[[Compressor, bool], nx.Graph], Depends(get_resolver)],
):
    """Return graph information, if present"""
    G = resolver(request.state.compressor, not url_crawled)
    return GraphInfo(
        num_nodes=len(G.nodes()),
        num_edges=len(G.edges()),
    )


@app.post("/queue-website/")
async def queue_website(
    request: Request,
    queue_url: QueueUrl,
    url_valid: Annotated[None, Depends(validate_url)],
    url_crawled: Annotated[None, Depends(queued_url_in_crawled)],
):
    """Append website for crawling and return status"""
    if not queue_url.force:
        raise HTTPException(status_code=409, detail="Already Crawled")
    await request.state.task_queue.queue.put(queue_url.url)
    return JSONResponse(
        status_code=201,
        content={
            "message": "Queued for Crawling",
            "position": request.state.task_queue.queue.qsize(),
        },
    )


@app.get("/stream-graph")
async def stream_graph(
    request: Request,
    url: str,
    url_crawled: Annotated[None, Depends(url_in_crawled)],
    resolver: Annotated[Callable[[Compressor, bool], nx.Graph], Depends(get_resolver)],
) -> StreamingResponse:
    G: nx.Graph = resolver(request.state.compressor, not url_crawled)
    response = StreamingResponse(
        content=generate_graph(G), media_type="application/json"
    )
    return response


@app.post("/move-into-node", response_model=AdjList)
async def move_into_node(
    request: Request,
    url: str,
    node: Node,
    url_crawled: Annotated[None, Depends(url_in_crawled)],
    resolver: Annotated[Callable[[Compressor, bool], nx.Graph], Depends(get_resolver)],
):
    """Return the neighbourhood of a node instance in a graph
    :param url: root url of graph
    :param node: Node model instance
    """
    G = resolver(request.state.compressor, not url_crawled)
    neighborhood = get_neighborhood(G, node)
    return neighborhood
