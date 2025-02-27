import sqlite3
from enum import Enum
from functools import cached_property
from typing import Dict, List, Protocol
from uuid import uuid4

import orjson
from pydantic import BaseModel, Field, ValidationError
from pymemcache.client.base import PooledClient
from pymemcache.exceptions import MemcacheError

from .models import CourseComplete, CourseModifiersHidden, CourseTracker


class StorageEngine(Enum):
    DICT = 0
    SQLITE = 1


class LeaderboardName(BaseModel):
    course_url: str
    moves: int

    @cached_property
    def key(self) -> str:
        return f"{self.course_url}:{self.moves}"


class LeaderboardDisplay(BaseModel):
    uid: str = Field(default_factory=lambda _: uuid4().hex)
    nickname: str
    score: float
    course_uid: str
    stamp: str


class LeaderboardTracker(CourseTracker):
    pass


class LeaderboardComplete(CourseComplete):
    pass


class ILeaderboardRepository(Protocol):
    def init_leaderboard(self, course_url: str, moves: int) -> None:
        """Create a new leaderboard for a course url and move combination"""
        ...

    def query_leaderboard(
        self, course_url: str, max_moves: int, start: int = 0, limit: int | None = 100
    ) -> List[LeaderboardDisplay]:
        """Return the leaderboard for a course url and move combination for a given range"""
        ...

    def drop_leaderboard(self, course_url: str, max_moves: int) -> None:
        """Drop the leaderboard for a course url"""
        ...

    def invalidate(self, entry_id) -> None:
        """Remove an entry from any leaderboard"""
        ...

    def update_leaderboard(
        self, course_url: str, max_moves: int, entry: LeaderboardDisplay
    ) -> None:
        """Add an entry to a leaderboard"""
        ...

    def course_exists(self, course_url: str, max_moves: int, course_uid: str) -> bool:
        """Query leaderboards to find a course uid from Display objects"""
        ...

    def queue_tracker_object(self, entry: LeaderboardComplete) -> None:
        """Dump tracker object to permanent storage"""
        ...

    def write_tracker_object(self, entry: LeaderboardComplete) -> None:
        """Dump tracker object to permanent storage"""
        ...

    def read_tracker_object(self, course_id: str) -> LeaderboardTracker | None:
        """Read tracker object from permanent storage"""
        ...

    def query_course_trackers(
        self, course_url: str, max_moves: int, start: int = 0, limit: int | None = 100
    ) -> List[LeaderboardTracker]:
        """Return the tracker objects for a course url and move combination for a given range"""
        ...

    def delete_tracker_object(self, course_id: str) -> None:
        """Delete tracker object from permanent storage"""
        ...


class DictLeaderboardRepository:
    def __init__(self):
        self.leaderboards: Dict[str, List[LeaderboardDisplay]] = dict()
        self.trackers: Dict[str, LeaderboardTracker] = dict()

    def init_leaderboard(self, course_url: str, moves: int) -> None:
        leaderboard_key = LeaderboardName(course_url=course_url, moves=moves).key
        if leaderboard_key in self.leaderboards.keys():
            return
        self.leaderboards[leaderboard_key] = list()

    def query_leaderboard(
        self, course_url: str, max_moves: int, start: int = 0, limit: int | None = 100
    ) -> List[LeaderboardDisplay]:
        leaderboard = self.leaderboards.get(
            LeaderboardName(course_url=course_url, moves=max_moves).key, []
        )
        if not leaderboard:
            return []
        if not limit:
            return leaderboard[start:]
        return leaderboard[start : start + limit]

    def drop_leaderboard(self, course_url: str, max_moves: int) -> None:
        key = LeaderboardName(course_url=course_url, moves=max_moves).key
        leaderboard = self.leaderboards.get(key, [])
        if not leaderboard:
            return
        self.leaderboards.pop(key)

    def invalidate(self, entry_id) -> None:
        for leaderboard in self.leaderboards:
            if entry_id in self.leaderboards[leaderboard]:
                self.leaderboards[leaderboard].remove(entry_id)
                break

    def update_leaderboard(
        self, course_url: str, max_moves: int, entry: LeaderboardDisplay
    ) -> None:
        self.leaderboards[
            LeaderboardName(course_url=course_url, moves=max_moves).key
        ].append(entry)
        self._sort_leaderboard(course_url, max_moves)

    def course_exists(self, course_url: str, max_moves: int, course_uid: str) -> bool:
        return course_uid in [
            display.course_uid
            for display in self.query_leaderboard(
                course_url=course_url,
                max_moves=max_moves,
                limit=None,
            )
        ]

    def queue_tracker_object(self, entry: LeaderboardComplete) -> None:
        self.write_tracker_object(entry)

    def write_tracker_object(self, entry: LeaderboardComplete) -> None:
        key = f"{entry.url}:{entry.tracker.move_tracker.moves_target}:{entry.uid}"
        self.trackers[key] = entry.tracker

    def read_tracker_object(self, course_id: str) -> LeaderboardTracker | None:
        trackers = {
            tracker_key: tracker
            for tracker_key, tracker in self.trackers.items()
            if course_id == tracker_key.split(":")[-1]
        }
        if not trackers.keys():
            return None
        return trackers[list(trackers.keys())[-1]]

    def query_course_trackers(
        self, course_url: str, max_moves: int, start: int = 0, limit: int | None = 100
    ) -> List[LeaderboardTracker]:
        trackers = [
            tracker
            for tracker_key, tracker in self.trackers.items()
            if course_url == tracker_key.split(":")[0]
            and max_moves == int(tracker_key.split(":")[1])
        ]
        if not limit:
            return trackers[start:]
        return trackers[start : start + limit]

    def delete_tracker_object(self, course_id: str) -> None:
        trackers = {
            tracker_key: tracker
            for tracker_key, tracker in self.trackers.items()
            if course_id == tracker_key.split(":")[-1]
        }
        if not trackers.keys():
            return None
        del self.trackers[list(trackers.keys())[-1]]

    def _sort_leaderboard(self, course_url: str, max_moves: int) -> None:
        _key = LeaderboardName(course_url=course_url, moves=max_moves).key
        leaderboard = self.leaderboards.get(_key, list())
        self.leaderboards[_key] = sorted(
            leaderboard, key=lambda x: x.score, reverse=True
        )


class SQLiteLeaderboardRepository:
    def __init__(self):
        pass


def _match_engine(engine: StorageEngine) -> ILeaderboardRepository:
    match engine:
        case StorageEngine.DICT:
            return DictLeaderboardRepository()
        case StorageEngine.SQLITE:
            return SQLiteLeaderboardRepository()


class ICacheRepository(Protocol):
    def course_exists(self, course_id: str) -> bool: ...
    def get_course(self, course_id: str) -> CourseComplete | None: ...
    def get_course_modifiers(self, course_id: str) -> CourseModifiersHidden | None: ...
    def set_course(self, course_id: str, course: CourseComplete): ...
    def set_course_modifiers(
        self, course_id: str, modifiers: CourseModifiersHidden
    ) -> None: ...
    def delete_course(self, course_id: str): ...
    def write_to_storage(self, course_id: str): ...


class DictCacheRepository:
    def __init__(self, storage_engine: StorageEngine):
        self.storage_engine: ILeaderboardRepository = _match_engine(storage_engine)
        self.client: Dict[str, CourseTracker] = dict()
        self.client_modifiers: Dict[str, CourseModifiersHidden] = dict()

    def course_exists(self, course_id: str) -> bool:
        return self.client.get(course_id, None) and self.client_modifiers.get(
            course_id, None
        )

    def get_course(self, course_id: str) -> CourseComplete | None:
        return self.client.get(course_id, None)

    def get_course_modifiers(self, course_id: str) -> CourseModifiersHidden | None:
        return self.client_modifiers.get(course_id, None)

    def set_course(self, course_id: str, course: CourseComplete) -> None:
        self.client[course_id] = course

    def set_course_modifiers(
        self, course_id: str, modifiers: CourseModifiersHidden
    ) -> None:
        self.client_modifiers[course_id] = modifiers

    def delete_course(self, course_id: str) -> None:
        del self.client[course_id]
        del self.client_modifiers[course_id]

    def write_to_storage(self, course_id: str) -> None:
        tracker = self.client.get(course_id, None)
        if not tracker:
            return
        try:
            self.storage_engine.queue_tracker_object(tracker)
        except Exception:
            return


class MemcachedCacheRepository:
    def __init__(self, storage_engine: StorageEngine):
        self.storage_engine: ILeaderboardRepository = _match_engine(storage_engine)
        self.client: PooledClient = PooledClient("localhost", 11211)
        self.course_index: List[str] = list()
        self.client.flush_all()

    def get_course(self, course_id: str) -> CourseTracker | None:
        if course_id not in self.course_index:
            return None

        tracker: bytes | None = self.client.get(course_id)
        if not tracker:
            return None
        try:
            return CourseTracker(**orjson.loads(tracker))
        except orjson.JSONDecodeError:
            return None
        except ValidationError:
            return None

    def set_course(self, course_id: str, course: CourseTracker):
        try:
            self.client.set(course_id, course.model_dump_json())
        except MemcacheError:
            return
        self.course_index.append(course_id)

    def delete_course(self, course_id: str):
        try:
            self.client.delete(course_id)
        except MemcacheError:
            return
        self.course_index.remove(course_id)

    def write_to_storage(self, course_id: str):
        tracker_bytes: bytes | None = self.client.get(course_id)
        if not tracker_bytes:
            return
        tracker = CourseTracker(**orjson.loads(tracker_bytes))

        try:
            self.storage_engine.queue_tracker_object(course_id, tracker)
        except Exception:
            return
