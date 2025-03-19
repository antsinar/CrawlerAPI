from __future__ import annotations

import inspect
import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Generator, List
from uuid import uuid4

import orjson
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.models import (
    LeaderboardComplete,
    LeaderboardDisplay,
    LeaderboardName,
    LeaderboardTracker,
)
from src.Stores.errors import DatabaseBusyError

logger = logging.getLogger(__name__)


class DictLeaderboardRepository:
    def __init__(self):
        self.leaderboards: Dict[str, List[LeaderboardDisplay]] = dict()
        self.trackers: Dict[str, LeaderboardTracker] = dict()

    def backup(self, path: str) -> None:
        (Path(__file__).parent / f"{path}.leaderboards").write_bytes(
            orjson.dumps(self.leaderboards)
        )
        (Path(__file__).parent / f"{path}.trackers").write_bytes(
            orjson.dumps(self.trackers)
        )

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
        self.busy = False
        self._set_pragma()

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
            result = session.execute(
                text(
                    """INSERT INTO leaderboard (course_url, moves)
                       VALUES (:course_url, :moves)
                       ON CONFLICT DO NOTHING
                       RETURNING uid;
                    """
                ),
                {"course_url": course_url, "moves": moves},
            )
            if not result.fetchone():
                logger.error(
                    f"Failed to create leaderboard for url {course_url} and moves {moves}"
                )
                session.rollback()
                return
            session.commit()

    def query_leaderboard(
        self, course_url: str, max_moves: int, start: int = 0, limit: int | None = 100
    ) -> List[LeaderboardDisplay]:
        with sessionmaker(self.engine)() as session:
            entries = session.execute(
                text(
                    """SELECT d.uid, d.nickname, d.score, d.course_uid, d.stamp FROM leaderboard_display d
                       INNER JOIN leaderboard l
                       ON d.leaderboard_uid = l.uid
                       WHERE l.course_url = :course_url AND l.moves = :moves
                       ORDER BY d.score DESC
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
                       RETURNING uid;
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
                return
            session.commit()

    def invalidate(self, entry_id) -> None:
        raise NotImplementedError

    def update_leaderboard(
        self,
        course_url: str,
        max_moves: int,
        entry: LeaderboardDisplay,
        tracker_uid: str,
    ) -> None:
        with sessionmaker(self.engine)() as session:
            result = session.execute(
                text(
                    """INSERT INTO leaderboard_display
                       (leaderboard_uid, uid, nickname, score, course_uid, tracker_uid)
                       VALUES (
                            (SELECT uid FROM leaderboard WHERE course_url = :course_url AND moves = :moves),
                            :display_uid, :nickname, :score, :course_uid, :tracker_uid
                       )
                       RETURNING uid;
                    """
                ),
                {
                    "course_url": course_url,
                    "moves": max_moves,
                    "display_uid": entry.uid,
                    "nickname": entry.nickname,
                    "score": entry.score,
                    "course_uid": entry.course_uid,
                    "tracker_uid": tracker_uid,
                },
            )
            entry_id = result.fetchone()
            if not entry_id:
                logger.error(f"Failed to insert {entry}")
                session.rollback()
                return
            session.commit()

    def course_exists(self, course_url: str, max_moves: int, course_uid: str) -> bool:
        with sessionmaker(self.engine)() as session:
            entries = session.execute(
                text(
                    """SELECT d.course_uid FROM leaderboard_display d
                       INNER JOIN leaderboard l
                       ON d.leaderboard_uid = l.uid
                       WHERE l.course_url = :course_url AND l.moves = :moves
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
        self.write_tracker_object(entry)

    def write_tracker_object(self, entry: LeaderboardComplete) -> None:
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
                tracker_uid = result.fetchone()
                if not tracker_uid:
                    logger.error(
                        f"Failed to insert tracker object for course {entry.uid}"
                    )
                    session.rollback()
                    return
                session.commit()
                return tracker_uid[0]

    def read_tracker_object(self, course_id: str) -> LeaderboardTracker | None:
        with sessionmaker(self.engine)() as session:
            tracker = session.execute(
                text(
                    """SELECT data FROM leaderboard_tracker t
                       INNER JOIN leaderboard_display d
                       ON t.uid = d.tracker_uid
                       WHERE d.course_uid = :course_uid
                    """
                ),
                {"course_uid": course_id},
            )
            result = tracker.fetchone()
            if not result:
                return None
            try:
                return LeaderboardTracker(**orjson.loads(result[-1]))
            except orjson.JSONDecodeError:
                return None

    def query_course_trackers(
        self, course_url: str, max_moves: int, start: int = 0, limit: int | None = 100
    ) -> List[LeaderboardTracker]:
        with sessionmaker(self.engine)() as session:
            trackers = session.execute(
                text(
                    """SELECT data FROM leaderboard_tracker t
                       INNER JOIN leaderboard_display d
                       ON t.uid = d.tracker_uid
                       INNER JOIN leaderboard l
                       ON d.leaderboard_uid = l.uid
                       WHERE l.course_url = :course_url
                       AND l.moves = :moves
                       ORDER BY d.score DESC
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
