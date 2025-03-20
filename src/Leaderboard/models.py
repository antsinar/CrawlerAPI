from __future__ import annotations

from functools import cached_property
from uuid import uuid4

from pydantic import BaseModel, Field

from src.Course.models import CourseComplete, CourseTracker


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
