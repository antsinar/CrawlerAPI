import asyncio
from contextlib import asynccontextmanager
from importlib import import_module
from os import environ
from typing import Annotated, List, Optional
from urllib.parse import ParseResult, urlparse

import networkx as nx
from dotenv import find_dotenv, load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse

from .constants import GRAPH_ROOT, Compressor, compressor_extensions
from .lib import extract_graph, generate_graph, get_crawled_urls, validate_url
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
        detail={"message": "Server Unavailable due to maintenance"},
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
async def graphs():
    """Return already crawled website graphs"""
    return {
        "crawled_urls": await get_crawled_urls(),
    }


@app.get("/graphs/")
async def graph_info(
    request: Request,
    url: str,
    crawled_urls: Annotated[List[str], Depends(get_crawled_urls)],
):
    """Return graph information, if present"""
    parsed: ParseResult = urlparse(url)
    if parsed.netloc not in crawled_urls:
        return JSONResponse(
            status_code=404, content={"message": "Website not yet crawled"}
        )
    compressor_module = import_module(request.state.compressor.value)
    G: Optional[nx.Graph] = await extract_graph(
        url, compressor_module, compressor_extensions[request.state.compressor.value]
    )
    if not G:
        return JSONResponse(
            status_code=404, content={"message": "Website not yet crawled"}
        )
    return GraphInfo(
        num_nodes=len(G.nodes()),
        num_edges=len(G.edges()),
    )


@app.post("/queue-website/")
async def queue_website(
    request: Request,
    queue_url: QueueUrl,
    crawled_urls: Annotated[List[str], Depends(get_crawled_urls)],
):
    """Append website for crawling and return status"""
    if not await validate_url(queue_url.url):
        return JSONResponse(status_code=400, content={"message": "Invalid URL"})
    parsed_url = urlparse(queue_url.url)
    if parsed_url.netloc in crawled_urls and not queue_url.force:
        return JSONResponse(status_code=409, content={"message": "Already Crawled"})
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
    crawled_urls: Annotated[List[str], Depends(get_crawled_urls)],
) -> StreamingResponse:
    if urlparse(url).netloc not in crawled_urls:
        return JSONResponse(
            status_code=404, content={"message": "Website not yet crawled"}
        )
    compressor_module = import_module(request.state.compressor.value)
    G: Optional[nx.Graph] = await extract_graph(
        url, compressor_module, compressor_extensions[request.state.compressor.value]
    )
    if not G:
        return JSONResponse(
            status_code=404, content={"message": "Website not yet crawled"}
        )

    response = StreamingResponse(
        content=generate_graph(G), media_type="application/json"
    )
    return response
