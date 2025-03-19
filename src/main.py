import asyncio
import logging
from contextlib import asynccontextmanager
from os import environ
from pathlib import Path
from urllib.parse import urlparse

import orjson
from dotenv import find_dotenv, load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import RedirectResponse
from starlette.concurrency import iterate_in_threadpool

from src.constants import (
    GRAPH_ROOT,
    HTTP_SCHEME,
    Compressor,
    ConcurrentRequestLimit,
    CrawlDepth,
)
from src.Course.router import router as course_router
from src.Crawler.processor import TaskQueue
from src.Crawler.router import router as crawler_router
from src.Graph.management import GraphCleaner, GraphInfoUpdater, GraphWatcher
from src.Graph.router import router as graph_router
from src.Leaderboard.router import router as leaderboard_router
from src.Stores.Repositories.CacheRepository import DictCacheRepository, StorageEngine
from src.Stores.Repositories.LeaderboardRepository import SQLiteLeaderboardRepository

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
        loop.create_task(watchdog.watch_files(cleaner, info_updater))
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


app.include_router(course_router)
app.include_router(crawler_router)
app.include_router(graph_router)
app.include_router(leaderboard_router)


@app.get("/", include_in_schema=False)
async def root(request: Request):
    """Redirect to docs, if not in production"""
    return (
        RedirectResponse(url="/docs")
        if request.app.state.environment != "production"
        else RedirectResponse(url="/graphs/all")
    )
