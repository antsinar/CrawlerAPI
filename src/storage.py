from __future__ import annotations

import asyncio
import inspect
import logging
from contextlib import contextmanager
from enum import Enum
from queue import Queue
from typing import Dict, Generator, List
from uuid import uuid4

import orjson
from pydantic import ValidationError
from pymemcache.client.base import PooledClient
from pymemcache.exceptions import MemcacheError
from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import sessionmaker

from .interfaces import ILeaderboardRepository
from .models import (
    CourseComplete,
    CourseModifiersHidden,
    CourseTracker,
    LeaderboardComplete,
    LeaderboardDisplay,
    LeaderboardName,
    LeaderboardTracker,
)

logger = logging.getLogger(__name__)


class DatabaseBusyError(Exception):
    pass


class StorageEngine(Enum):
    DICT = 0
    SQLITE = 1


class DictLeaderboardRepository:
    def __init__(self):
        self.leaderboards: Dict[str, List[LeaderboardDisplay]] = dict()
        self.trackers: Dict[str, LeaderboardTracker] = dict()

    def backup(self, path: str) -> None:
        pass

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
    def __init__(self, database_uri: str):
        self.database_uri = database_uri
        self.engine = create_engine(self.database_uri)
        self.tracker_queue: Queue[LeaderboardComplete] = Queue()
        self.busy = False
        self.loop = asyncio.get_running_loop()
        self.loop.run_in_executor(self._watch_tracker_queue())

    @event.listens_for(Engine, "connect", once=True)
    def _set_pragma(self) -> None:
        with self._flag_busy():
            connection = self.engine.connect()
            connection.execute(text("PRAGMA foreign_keys=ON"))
            connection.execute(text("PRAGMA JOURNAL_MODE=WAL"))
            connection.commit()
            connection.close()

    @contextmanager
    def _flag_busy(self) -> Generator[None, None, None]:
        try:
            if self.busy:
                raise DatabaseBusyError("Database is currently busy")
            self.busy = True
            logger.info("Database write lock aquired")
            yield
            self.busy = False
            logger.info("Database write lock released")
        except DatabaseBusyError as dbe:
            logger.error(dbe)

    def backup(self, path: str) -> None:
        with self._flag_busy():
            connection = self.engine.connect()
            connection.execute(text(".backup :path"), {"path": path})
            connection.close()

    def init_leaderboard(self, course_url: str, moves: int) -> None:
        with sessionmaker(self.engine)() as session:
            session.execute(
                text(
                    """INSERT INTO leaderboard (course_url, moves)
                       VALUES (:course_url, :moves)
                       ON CONFLICT DO NOTHING
                    """
                ),
                {"course_url": course_url, "moves": moves},
            )
            # TODO: update index here
            session.commit()

    def query_leaderboard(
        self, course_url: str, max_moves: int, start: int = 0, limit: int | None = 100
    ) -> List[LeaderboardDisplay]:
        with sessionmaker(self.engine)() as session:
            entries = session.execute(
                text(
                    """SELECT uid, nickname, score, course_uid, stamp FROM leaderboard_display display
                       INNER JOIN leaderboard
                       ON leaderboard_display.leaderboard_id = leaderboard.id
                       WHERE leaderboard.course_url = :course_url AND leaderboard.moves = :moves
                       ORDER BY display.score DESC
                       LIMIT :limit OFFSET :start
                    """
                ),
                {
                    "course_url": course_url,
                    "moves": max_moves,
                    "start": start,
                    "limit": limit,
                },
            )
            result = entries.fetchall()
            if not result:
                return list()
            display_keys = inspect.signature(LeaderboardDisplay).parameters.keys()
            return [
                LeaderboardDisplay(**{el[0]: el[1] for el in zip(display_keys, entry)})
                for entry in result
            ]

    def drop_leaderboard(self, course_url: str, max_moves: int) -> None:
        with sessionmaker(self.engine)() as session:
            result = session.execute(
                text(
                    """DELETE FROM leaderboard
                       WHERE course_url = :course_url
                       AND moves = :moves
                       RETURNING uid
                       """
                ),
                {"course_url": course_url, "moves": max_moves},
            )
            ids = result.fetchall()
            if not ids:
                logger.error(
                    "Leaderboard with course url %s and moves %s not found"
                    % (course_url, max_moves)
                )
                session.rollback()
            session.commit()

    def invalidate(self, entry_id) -> None:
        raise NotImplementedError

    def update_leaderboard(
        self, course_url: str, max_moves: int, entry: LeaderboardDisplay
    ) -> None:
        with sessionmaker(self.engine)() as session:
            result = session.execute(
                text(
                    """INSERT INTO leaderboard_display
                       (leaderboard_uid, uid, nickname, score, course_uid, stamp)
                       VALUES (
                        (SELECT uid FROM leaderboard WHERE course_url = :course_url AND moves = :moves),
                        :uid, :nickname, :score, :course_uid, :stamp
                       )
                       RETURNING uid
                    """
                ),
                {
                    "course_url": course_url,
                    "moves": max_moves,
                    "uid": entry.uid,
                    "nickname": entry.nickname,
                    "score": entry.score,
                    "course_uid": entry.course_uid,
                    "stamp": entry.stamp,
                },
            )
            entry_id = result.fetchone()
            if not entry_id:
                logger.error(f"Failed to insert {entry}")
                session.rollback()
            session.commit()

    def course_exists(self, course_url: str, max_moves: int, course_uid: str) -> bool:
        with sessionmaker(self.engine)() as session:
            entries = session.execute(
                text(
                    """SELECT course_uid FROM leaderboard_display display
                       INNER JOIN leaderboard
                       ON leaderboard_display.leaderboard_uid = leaderboard.uid
                       WHERE leaderboard.course_url = :course_url AND leaderboard.moves = :moves
                    """
                ),
                {
                    "course_url": course_url,
                    "moves": max_moves,
                },
            )
            result = entries.fetchall()
            return course_uid in [el[0] for el in result]

    def queue_tracker_object(self, entry: LeaderboardComplete) -> None:
        self.tracker_queue.put(entry)

    def write_tracker_object(self, entry: LeaderboardComplete) -> None:
        if not self.course_exists(
            entry.url, entry.tracker.move_tracker.moves_target, entry.uid
        ):
            logger.error("Course with uid %s not found", entry.uid)
            return

        with self._flag_busy():
            with sessionmaker(self.engine)() as session:
                result = session.execute(
                    text(
                        """INSERT INTO leaderboard_tracker
                          (uid, data)
                          VALUES (:uid, :data)
                          RETURNING uid
                        """
                    ),
                    {"uid": uuid4().hex, "data": entry.tracker.model_dump_json()},
                )
                if not result.fetchone():
                    logger.error(
                        f"Failed to insert tracker object for course {entry.uid}"
                    )
                    session.rollback()
                session.commit()

    def read_tracker_object(self, course_id: str) -> LeaderboardTracker | None:
        with sessionmaker(self.engine)() as session:
            tracker = session.execute(
                text(
                    """SELECT data FROM leaderboard_tracker tracker
                       INNER JOIN leaderboard_display display
                       ON tracker.uid = display.tracker_uid
                       WHERE display.course_uid = :course_uid
                    """
                ),
                {"course_uid": course_id},
            )
            result = tracker.fetchone()
            if not result:
                return None
            try:
                return LeaderboardTracker(**orjson.loads(result[1]))
            except orjson.JSONDecodeError:
                return None

    def query_course_trackers(
        self, course_url: str, max_moves: int, start: int = 0, limit: int | None = 100
    ) -> List[LeaderboardTracker]:
        with sessionmaker(self.engine)() as session:
            trackers = session.execute(
                text(
                    """SELECT data FROM leaderboard_tracker tracker
                       INNER JOIN leaderboard_display display
                       ON tracker.uid = display.tracker_uid
                       INNER JOIN leaderboard
                       ON display.leaderboard_uid = leaderboard.uid
                       WHERE leaderboard.course_url = :course_url
                       AND leaderboard.moves = :moves
                       ORDER BY display.score DESC
                       LIMIT :limit OFFSET :start
                    """
                ),
                {
                    "course_url": course_url,
                    "moves": max_moves,
                    "start": start,
                    "limit": limit,
                },
            )
            results = trackers.fetchall()
            if not results:
                return list()
            try:
                return [LeaderboardTracker(**orjson.loads(el[0])) for el in results]
            except orjson.JSONDecodeError:
                logger.error("Failed to decode tracker object")
                return list()

    def delete_tracker_object(self, course_id: str) -> None:
        raise NotImplementedError

    def _watch_tracker_queue(self):
        while True:
            if self.tracker_queue.empty() or self.busy:
                continue
            entry = self.tracker_queue.get()
            self.write_tracker_object(entry)
            self.tracker_queue.task_done()


def _match_engine(engine: StorageEngine) -> ILeaderboardRepository:
    match engine:
        case StorageEngine.DICT:
            return DictLeaderboardRepository()
        case StorageEngine.SQLITE:
            return SQLiteLeaderboardRepository()


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
