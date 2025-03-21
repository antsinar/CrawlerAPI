from pathlib import Path

from src.constants import Compressor, ConcurrentRequestLimit, CrawlDepth
from src.Stores.interfaces import ICacheRepository, ILeaderboardRepository
from src.Stores.Repositories.CacheRepository import DictCacheRepository
from src.Stores.Repositories.LeaderboardRepository import (
    DictLeaderboardRepository,
    SQLiteLeaderboardRepository,
)


async def _match_compressor(compressor: str) -> Compressor:
    match compressor:
        case "lzma":
            return Compressor.LZMA
        case "gzip":
            return Compressor.GZIP
        case _:
            return Compressor.LZMA


async def _match_crawl_depth(crawl_depth: str) -> CrawlDepth:
    match crawl_depth:
        case "shallow":
            return CrawlDepth.SHALLOW
        case "average":
            return CrawlDepth.AVERAGE
        case "deep":
            return CrawlDepth.DEEP
        case _:
            return CrawlDepth.AVERAGE


async def _match_request_limit(request_limit: str) -> ConcurrentRequestLimit:
    match request_limit:
        case "gentle":
            return ConcurrentRequestLimit.GENTLE
        case "average":
            return ConcurrentRequestLimit.AVERAGE
        case "aggressive":
            return ConcurrentRequestLimit.AGGRESIVE
        case _:
            return ConcurrentRequestLimit.AVERAGE


async def _match_leaderboard_type(leaderboard_type: str) -> ILeaderboardRepository:
    match leaderboard_type:
        case "sqlite":
            return SQLiteLeaderboardRepository(
                database_uri="sqlite:///%s"
                % (Path(__file__).parent.parent / "database.db").as_posix()
            )
        case _:
            return DictLeaderboardRepository()


async def _match_cache_type(
    cache_type: str, storage_engine: ILeaderboardRepository
) -> ICacheRepository:
    match cache_type:
        case _:
            return DictCacheRepository(storage_engine=storage_engine)
