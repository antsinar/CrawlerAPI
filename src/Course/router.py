from __future__ import annotations

import random
from typing import Annotated, Callable, List

import networkx as nx
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Body,
    Depends,
    HTTPException,
    Request,
    status,
)

from src.constants import (
    HTTPS_SCHEME,
    MAX_TRAPS_TRIGGERED,
    Compressor,
    Difficulty,
    MoveOptions,
    difficulty_ranges,
)
from src.Course.models import (
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
    NodeInCourse,
    NodePoints,
    NodePowerup,
)
from src.Course.tasks import (
    calc_move_multiplier,
    calc_node_points,
    initialize_course,
    write_to_leaderboard,
)
from src.Graph.dependencies import (
    GraphResolver,
    get_resolver_from_object,
    graph_resolvers,
    resolve_graph_from_course_object,
    url_in_crawled_from_object,
)
from src.Graph.models import Node
from src.Stores.interfaces import ICacheRepository

router = APIRouter(prefix="/course", tags=["course"])


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
    if not possible_urls:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Could not find course with difficulty {difficulty}",
        )
    random.shuffle(possible_urls)
    return {"url": random.choice(possible_urls)}


@router.post("/begin", response_model=CourseComplete)
async def course_begin(
    request: Request,
    url: Annotated[str, Body(embed=True)],
    moves_target: Annotated[
        MoveOptions, Body(default_factory=lambda _: random.choice(list(MoveOptions)))
    ],
    url_crawled: Annotated[None, Depends(url_in_crawled_from_object)],
    resolver: Annotated[
        Callable[[Compressor, bool], nx.Graph], Depends(get_resolver_from_object)
    ],
    tasks: BackgroundTasks,
):
    """Initialize a tracker object for a playable course and perform modifications"""
    G = resolver(request.app.state.compressor, True)
    nodes_list = list(G.nodes)
    source = Node(id=random.choice(nodes_list))
    tracker = CourseTracker(
        move_tracker=CourseMoveTracker(moves_target=moves_target),
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


@router.post("/get-neighborhood", response_model=AdjListPoints)
async def get_node_neighborhood(
    request: Request,
    current_node: NodeInCourse,
    resolver: Annotated[nx.Graph, Depends(resolve_graph_from_course_object)],
):
    G: nx.Graph = resolver(request.app.state.compressor, True)
    cache_storage: ICacheRepository = request.app.state.cacheRepository
    course: CourseComplete = cache_storage.get_course(current_node.uid)
    if not course:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Course not found"
        )
    modifiers: CourseModifiersHidden | None = cache_storage.get_course_modifiers(
        current_node.uid
    )
    if not modifiers:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unexpected cache error",
        )
    # TODO: check traps and powerups

    # trap nodes are hidden
    powerup_nodes = [
        node
        for node in modifiers.powerups.keys()
        if node in G.neighbors(current_node.node.id)
    ]
    # powerup_nodes = [*modifiers.powerups.keys()]
    active_modifiers = [*modifiers.triggered_traps, *modifiers.active_powerups]
    try:
        teleport_nodes = [
            node.id
            for node in request.app.state.info_updater.graph_info[
                HTTPS_SCHEME + course.url
            ].teleport_nodes
        ]
    except KeyError:
        teleport_nodes = list()

    adj_list = AdjListPoints(
        source=NodePoints(id=current_node.node.id, points=0),
        dest=[
            NodePoints(
                id=neighbor,
                points=calc_node_points(
                    G, course.start_node.id, neighbor, teleport_nodes
                ),
            )
            for neighbor in G.neighbors(current_node.node.id)
            if neighbor not in powerup_nodes
        ],
    )
    adj_list.dest.extend(
        [NodePowerup(id=key, powerup=modifiers.powerups[key]) for key in powerup_nodes]
    )
    # TODO: add trap or powerup effect

    return adj_list


@router.post("/move-into-node", response_model=CourseComplete)
async def move_into_node(
    request: Request,
    target_node: NodeInCourse,
    resolver: Annotated[nx.Graph, Depends(resolve_graph_from_course_object)],
    tasks: BackgroundTasks,
):
    """Move into a node and return the updated course tracker"""
    already_visited: bool = False
    cache_storage: ICacheRepository = request.app.state.cacheRepository
    course = cache_storage.get_course(target_node.uid)
    if not course:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Course not found"
        )
    course_modifiers = cache_storage.get_course_modifiers(target_node.uid)
    if not course_modifiers:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unexpected error in cache",
        )

    current_node = course.tracker.path_tracker.current_node
    if (
        target_node.node.id == current_node.id
        or course.game_state == GameState.FINISHED
    ):
        course.game_state = GameState.FINISHED
        tasks.add_task(
            write_to_leaderboard, request.app.state.leaderboardRepository, course
        )
        return course

    G: nx.Graph = resolver(request.app.state.compressor, True)

    if nx.shortest_path_length(G, current_node.id, target_node.node.id) != 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Nodes are not neighbors"
        )

    course.tracker.move_tracker.moves_taken += 1
    if target_node.node in course.tracker.path_tracker.movement_path:
        already_visited = True

    try:
        teleport_nodes: List[str] = [
            node.id
            for node in request.app.state.info_updater.graph_info[
                course.url
            ].teleport_nodes
        ]
    except KeyError:
        teleport_nodes = list()

    multiplier = calc_move_multiplier(course.tracker, target_node.node, teleport_nodes)
    course.tracker.path_tracker.movement_path.append(target_node.node)

    if target_node.node.id in teleport_nodes:
        new_node = Node(id=random.choice(teleport_nodes))
        course.tracker.path_tracker.teleport_nodes_used.append(target_node.node)
        course.tracker.path_tracker.movement_path.append(new_node)
        course.tracker.path_tracker.current_node = new_node
    else:
        course.tracker.path_tracker.current_node = target_node.node

    course.tracker.modifiers_tracker.active_powerups = [
        CoursePowerup(type=powerup.type, moves_left=powerup.moves_left - 1)
        for powerup in course.tracker.modifiers_tracker.active_powerups
        if powerup.moves_left > 1
    ]
    course.tracker.modifiers_tracker.triggered_traps = [
        CourseTrap(type=trap.type, moves_left=trap.moves_left - 1)
        for trap in course.tracker.modifiers_tracker.triggered_traps
    ]

    course.tracker.score_tracker.multiplier = multiplier
    if not already_visited:
        # gather node effect (points, trap, powerup)
        # TODO: Add trap effect
        # TODO: Add powerup effect
        course.tracker.score_tracker.points += (
            calc_node_points(
                G, course.start_node.id, target_node.node.id, teleport_nodes
            )
            * multiplier
        )

    try:
        cache_storage.set_course(course_id=target_node.uid, course=course)
        cache_storage.set_course_modifiers(
            course_id=target_node.uid, modifiers=course_modifiers
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Error writing to cache, {e}",
        )

    if (
        course.tracker.move_tracker.moves_taken
        == course.tracker.move_tracker.moves_target
        or len(course.tracker.modifiers_tracker.triggered_traps) >= MAX_TRAPS_TRIGGERED
    ):
        course.game_state = GameState.FINISHED

    return course
