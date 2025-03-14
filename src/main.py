import asyncio
import logging
from contextlib import asynccontextmanager
from os import environ
from pathlib import Path
from typing import Annotated, Callable, List
from urllib.parse import urlparse

import networkx as nx
import orjson
from dotenv import find_dotenv, load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.concurrency import iterate_in_threadpool

from .constants import (
    GRAPH_ROOT,
    HTTP_SCHEME,
    Compressor,
    ConcurrentRequestLimit,
    CrawlDepth,
)
from .dependencies import (
    get_crawled_urls,
    get_resolver,
    url_in_crawled,
    url_not_in_crawled_from_object,
    validate_url,
)
from .management import GraphCleaner, GraphInfoUpdater, GraphWatcher
from .models import GraphInfo, QueueUrl
from .processor import TaskQueue
from .routers.game import router as game_router
from .storage import (
    DictCacheRepository,
    DictLeaderboardRepository,
    SQLiteLeaderboardRepository,
    StorageEngine,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        load_dotenv(find_dotenv(".env"))
        environment = environ.get("ENV", "development")
        app.state.compressor = Compressor.LZMA
        app.state.environment = environment
        app.state.leaderboardRepository = SQLiteLeaderboardRepository(
            database_uri="sqlite:///%s"
            % (Path(__file__).parent.parent / "database.db").as_posix()
        )
        app.state.cacheRepository = DictCacheRepository(
            storage_engine=StorageEngine.DICT
        )
        GRAPH_ROOT.mkdir(exist_ok=True)
        task_queue = TaskQueue(
            compressor=app.state.compressor,
            capacity=1,
            crawl_depth=CrawlDepth.AVERAGE,
            request_limit=ConcurrentRequestLimit.AGGRESIVE,
        )
        app.state.task_queue = task_queue
        cleaner = GraphCleaner(app.state.compressor)
        info_updater = GraphInfoUpdater(app.state.compressor)
        watchdog = GraphWatcher(app.state.compressor)
        loop = asyncio.get_event_loop()
        async with asyncio.TaskGroup() as tg:
            tg.create_task(
                watchdog.run_scheduled_functions(
                    loop, [cleaner.sweep, info_updater.update_info]
                )
            )
        app.state.info_updater = info_updater
        app.state.active_courses = dict()
        processor = asyncio.create_task(task_queue.process_queue())
        asyncio.create_task(watchdog.watch_graphs(cleaner, info_updater))
        yield
    except Exception as e:
        pass
    finally:
        await task_queue.stop()
        await cleaner.stop()
        await info_updater.stop()
        await watchdog.stop()


app = FastAPI(
    lifespan=lifespan,
    openapi_url="/openapi.json"
    if environ.get("ENV", "development") != "production"
    else None,
)
app.add_middleware(GZipMiddleware, minimum_size=3000, compresslevel=7)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def append_new_course_to_app_state(request: Request, call_next):
    """If a new course is initialized, appends its uid and base url inside the application state"""
    if request.method == "POST" and request.url.path == "/course/begin":
        response = await call_next(request)
        resp_body = [chunk async for chunk in response.body_iterator]
        response.body_iterator = iterate_in_threadpool(iter(resp_body))
        resp_body = orjson.loads(resp_body[0])
        uid, url = resp_body.get("uid", None), resp_body.get("url", None)
        if not (uid and url):
            return response
        app.state.active_courses[uid] = urlparse(HTTP_SCHEME + url).netloc
        return response
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


app.include_router(game_router)


@app.get("/", include_in_schema=False)
async def root(request: Request):
    """Redirect to docs, if not in production"""
    return (
        RedirectResponse(url="/docs")
        if request.app.state.environment != "production"
        else RedirectResponse(url="/graphs/all")
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
    try:
        return request.app.state.info_updater.graph_info[urlparse(url).netloc]
    except KeyError:
        logger.info("Computing graph info")
        G = resolver(request.app.state.compressor, True)
        return GraphInfo(num_nodes=G.number_of_nodes(), num_edges=G.number_of_edges())


@app.post("/queue-website/")
async def queue_website(
    request: Request,
    queue_url: QueueUrl,
    url_valid: Annotated[None, Depends(validate_url)],
    url_crawled: Annotated[None, Depends(url_not_in_crawled_from_object)],
):
    """Append website for crawling and return status"""
    if not url_crawled and queue_url.force:
        raise HTTPException(status_code=409, detail="Already Crawled")
    await request.app.state.task_queue.push_url(queue_url.url)
    return JSONResponse(
        status_code=201,
        content={
            "message": "Queued for Crawling",
            "position": request.app.state.task_queue.get_size(),
        },
    )
