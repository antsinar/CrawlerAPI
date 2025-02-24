import random
from typing import Annotated, Callable

import networkx as nx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse

from src.constants import MAX_TRAPS_TRIGGERED, Compressor, Difficulty, difficulty_ranges
from src.dependencies import (
    GraphResolver,
    get_resolver,
    graph_resolvers,
    resolve_graph_from_course,
    url_in_crawled,
)
from src.models import (
    AdjListPoints,
    CourseComplete,
    CourseModifiersHidden,
    CourseModifiersTracker,
    CourseMoveTracker,
    CoursePathTracker,
    CoursePowerup,
    CourseScoreTracker,
    CourseTracker,
    CourseTrap,
    GameState,
    Node,
    NodePoints,
    NodePowerup,
)
from src.storage import ICacheRepository
from src.tasks.game import calc_move_multiplier, calc_node_points, initialize_course

router = APIRouter(prefix="/course")


@router.get("/generate-course-url")
async def generate_course_url(
    request: Request,
    difficulty: Difficulty,
    resolvers: Annotated[dict[str, GraphResolver], Depends(graph_resolvers)],
) -> dict[str, str]:
    """Return course url based on difficulty"""
    difficulty_range = difficulty_ranges[difficulty]
    possible_urls = [
        url
        for url in resolvers.keys()
        if request.app.state.info_updater.graph_info[url].num_nodes in difficulty_range
    ]
    random.shuffle(possible_urls)
    return {"url": random.choice(possible_urls)}


@router.post("/begin", response_model=CourseComplete)
async def course_begin(
    request: Request,
    url: str,
    url_crawled: Annotated[None, Depends(url_in_crawled)],
    resolver: Annotated[Callable[[Compressor, bool], nx.Graph], Depends(get_resolver)],
    tasks: BackgroundTasks,
):
    """Initialize a tracker object for a playable course and perform modifications"""
    G = resolver(request.app.state.compressor, True)
    nodes_list = list(G.nodes)
    source = Node(id=random.choice(nodes_list))
    tracker = CourseTracker(
        move_tracker=CourseMoveTracker(),
        score_tracker=CourseScoreTracker(),
        path_tracker=CoursePathTracker(
            current_node=source,
            movement_path=[
                source,
            ],
        ),
        modifiers_tracker=CourseModifiersTracker(),
    )
    course = CourseComplete(url=url, start_node=source, end_node=None, tracker=tracker)
    tasks.add_task(
        initialize_course,
        course=course,
        graph=G,
        cache_storage=request.app.state.cacheRepository,
        num_traps=10,
        num_powerups=10,
    )
    return course


@router.post("/get-neighbourhood", response_model=AdjListPoints)
async def get_node_neighbourhood(
    request: Request,
    uid: str,
    current_node: Node,
    resolver: Annotated[nx.Graph, Depends(resolve_graph_from_course)],
):
    G: nx.Graph = resolver(request.app.state.compressor, True)
    cache_storage: ICacheRepository = request.app.state.cacheRepository
    course: CourseComplete = cache_storage.get_course(uid)
    if not course:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Course not found"
        )
    modifiers: CourseModifiersHidden | None = cache_storage.get_course_modifiers(uid)
    if not modifiers:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unexpected cache error",
        )
    # TODO: check if the node can be searched by the player, according to the tracker object
    # TODO: check current node
    # TODO: check traps and powerups
    # TODO: check path

    # trap nodes are hidden
    powerup_nodes = [*modifiers.powerups.keys()]
    active_modifiers = [*modifiers.triggered_traps, *modifiers.active_powerups]
    adj_list = AdjListPoints(
        source=NodePoints(id=current_node.id, points=0),
        dest=[
            NodePoints(
                id=neighbour,
                points=calc_node_points(G, course.start_node.id, neighbour),
            )
            for neighbour in G.neighbors(current_node.id)
            if neighbour not in powerup_nodes
        ],
    )
    adj_list.dest.extend(
        [
            NodePowerup(id=key, powerup=value)
            for key, value in modifiers.powerups.items()
        ]
    )

    # TODO: add trap or powerup effect

    return adj_list


@router.post("/move-into-node", response_model=CourseComplete)
async def move_into_node(
    request: Request,
    uid: str,
    target_node: Node,
    resolver: Annotated[nx.Graph, Depends(resolve_graph_from_course)],
):
    """Move into a node and return the updated course tracker"""
    # get tracker object and find the current node
    cache_storage: ICacheRepository = request.app.state.cacheRepository
    course = cache_storage.get_course(uid)
    if not course:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Course not found"
        )
    course_modifiers = cache_storage.get_course_modifiers(uid)
    if not course_modifiers:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unexpected error in cache",
        )

    # check end condition (move type) -- submits exit node (current node)
    current_node = (
        course.tracker.path_tracker.current_node
        or course.game_state == GameState.FINISHED
    )
    if target_node.id == current_node.id:
        course.game_state = GameState.FINISHED
        return course

    # get course
    G: nx.Graph = resolver(request.app.state.compressor, True)

    # check if movement is valid (distance, traps, powerups)
    if nx.shortest_path(G, current_node.id, target_node.id) != 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Nodes are not neighbours"
        )

    # update tracker object (move, path, modifiers)
    course.tracker.move_tracker.moves_taken += 1
    course.tracker.path_tracker.movement_path.append(target_node)
    course.tracker.path_tracker.current_node = target_node
    course.tracker.modifiers_tracker.active_powerups = [
        CoursePowerup(type=powerup.type, moves_left=powerup.moves_left - 1)
        for powerup in course.tracker.modifiers_tracker.active_powerups
        if powerup.moves_left > 1
    ]
    course.tracker.modifiers_tracker.triggered_traps = [
        CourseTrap(type=trap.type, moves_left=trap.moves_left - 1)
        for trap in course.tracker.modifiers_tracker.triggered_traps
    ]

    # gather node effect (points, trap, powerup)
    # TODO: Add trap effect
    # TODO: Add powerup effect
    multiplier = calc_move_multiplier(course.tracker, target_node)
    course.tracker.score_tracker.multiplier = multiplier
    course.tracker.score_tracker.points += (
        calc_node_points(G, course.start_node.id, target_node.id) * multiplier
    )

    # submit tracker and modifiers to cache
    try:
        cache_storage.set_course(course_id=uid, course=course)
        cache_storage.set_course_modifiers(course_id=uid, modifiers=course_modifiers)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Error writing to cache, {e}",
        )
    # check end conditions (traps, moves)
    if (
        course.tracker.move_tracker.moves_taken
        == course.tracker.move_tracker.moves_target
        or len(course.tracker.modifiers_tracker.triggered_traps) >= MAX_TRAPS_TRIGGERED
    ):
        course.game_state = GameState.FINISHED

    return course


@router.get("/summary")
async def get_course_summary(request, course_uid: str):
    # get course from cache
    # produce course summary
    # get leaderboard
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented"
    )
