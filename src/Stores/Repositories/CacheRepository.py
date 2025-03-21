from __future__ import annotations

import logging
from enum import Enum
from typing import Dict, List

import orjson
from pydantic import ValidationError
from pymemcache.client.base import PooledClient
from pymemcache.exceptions import MemcacheError

from src.Course.models import CourseComplete, CourseModifiersHidden, CourseTracker
from src.Stores.interfaces import ILeaderboardRepository
from src.Stores.Repositories.LeaderboardRepository import (
    DictLeaderboardRepository,
    SQLiteLeaderboardRepository,
)

logger = logging.getLogger(__name__)


class StorageEngine(Enum):
    DICT = 0
    SQLITE = 1


def _match_engine(engine: StorageEngine) -> ILeaderboardRepository:
    match engine:
        case StorageEngine.DICT:
            return DictLeaderboardRepository()
        case StorageEngine.SQLITE:
            return SQLiteLeaderboardRepository()


class DictCacheRepository:
    def __init__(self, storage_engine: ILeaderboardRepository):
        self.storage_engine: ILeaderboardRepository = storage_engine
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
    def __init__(self, storage_engine: ILeaderboardRepository):
        self.storage_engine: ILeaderboardRepository = storage_engine
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
