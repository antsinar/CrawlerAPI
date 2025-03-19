from sqlalchemy import JSON, Float, ForeignKey, Integer, String
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    column_property,
    mapped_column,
    relationship,
)
from sqlalchemy.sql import func

# TODO: Enforce Unique constraint
# TODO: Implement Indexing


class Base(DeclarativeBase):
    pass


class Leaderboard(Base):
    __tablename__ = "leaderboard"

    uid: Mapped[int] = mapped_column(primary_key=True)
    course_url: Mapped[str] = mapped_column(String(100))
    moves: Mapped[int] = mapped_column(Integer())
    key = column_property(f"{course_url}:{moves}")

    entries: Mapped[list["LeaderboardDisplay"]] = relationship(
        back_populates="leaderboard"
    )


class LeaderboardDisplay(Base):
    __tablename__ = "leaderboard_display"

    uid: Mapped[str] = mapped_column(primary_key=True)
    course_uid: Mapped[str] = mapped_column(String(32))
    score: Mapped[float] = mapped_column(Float(precision=3))
    nickname: Mapped[str] = mapped_column(String(10))
    stamp: Mapped[str] = mapped_column(String(40), server_default=func.now())
    leaderboard_uid: Mapped[int] = mapped_column(ForeignKey("leaderboard.uid"))
    tracker_uid: Mapped[str] = mapped_column(ForeignKey("leaderboard_tracker.uid"))

    leaderboard: Mapped[Leaderboard] = relationship(back_populates="entries")
    tracker: Mapped["LeaderboardTracker"] = relationship(back_populates="display")

    def __repr__(self) -> str:
        return f"LeaderboardDisplay(uid={self.uid!r}, score={self.score!r}, nickname={self.nickname!r})"


class LeaderboardTracker(Base):
    __tablename__ = "leaderboard_tracker"

    uid: Mapped[str] = mapped_column(primary_key=True)
    data: Mapped[str] = mapped_column(JSON())

    display: Mapped[LeaderboardDisplay] = relationship(back_populates="tracker")

    def __repr__(self) -> str:
        return f"LeaderboardTracker(uid={self.uid!r}, course_uid={self.display.course_uid!r})"
