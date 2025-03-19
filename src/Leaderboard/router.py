from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Body, HTTPException, Request, status
from fastapi.responses import JSONResponse

from src.Course.models import GameState
from src.Course.tasks import write_to_leaderboard
from src.Leaderboard.models import LeaderboardTracker
from src.Stores.Repositories.CacheRepository import ICacheRepository
from src.Stores.Repositories.LeaderboardRepository import ILeaderboardRepository

router = APIRouter(prefix="/leaderboard", tags=["leaderboard"])


@router.post("/update-leaderboard")
async def update_leaderboard(
    request: Request, uid: Annotated[str, Body(embed=True)], tasks: BackgroundTasks
):
    cache_storage: ICacheRepository = request.app.state.cacheRepository
    course = cache_storage.get_course(uid)
    if not course:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Course not found in cache",
            headers={"X-Availability": "Not Available"},
        )
    if course.game_state != GameState.FINISHED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Course not yet finished",
            headers={"X-Availability": "Pending"},
        )
    leaderboard_storage: ILeaderboardRepository = (
        request.app.state.leaderboardRepository
    )
    if leaderboard_storage.course_exists(
        course_url=course.url,
        max_moves=course.tracker.move_tracker.moves_target.value,
        course_uid=uid,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Course already exists in leaderboard",
            headers={"X-Availability": "Available"},
        )
    tasks.add_task(write_to_leaderboard, leaderboard_storage, course)
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        headers={"X-Availability": "Available"},
        content={"message": "Adding course to leaderboard"},
    )


@router.get("/summary", response_model=LeaderboardTracker)
async def get_course_summary(request: Request, uid: str):
    cache_storage: ICacheRepository = request.app.state.cacheRepository
    course = cache_storage.get_course(uid)
    if course:
        return course.tracker

    leaderboard_storage: ILeaderboardRepository = (
        request.app.state.leaderboardRepository
    )
    tracker: LeaderboardTracker | None = leaderboard_storage.read_tracker_object(uid)
    if not tracker:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Course Tracker not found in storage",
        )

    return tracker
