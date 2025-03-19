from typing import List, Protocol

from src.models import (
    CourseComplete,
    CourseModifiersHidden,
    LeaderboardComplete,
    LeaderboardDisplay,
    LeaderboardTracker,
)


class ILeaderboardRepository(Protocol):
    def backup(self, path: str):
        """Backup the current state of the repository to permanent storage"""
        ...

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
        self,
        course_url: str,
        max_moves: int,
        entry: LeaderboardDisplay,
        tracker_uid: str,
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
