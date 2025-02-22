import random
from typing import Annotated, Callable

import networkx as nx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

from src.constants import Compressor, Difficulty, difficulty_ranges
from src.dependencies import (
    GraphResolver,
    get_resolver,
    graph_resolvers,
    resolve_graph_from_course,
    url_in_crawled,
)
from src.models import (
    AdjList,
    AdjListPoints,
    Course,
    CourseComplete,
    CourseModifiersHidden,
    CourseModifiersTracker,
    CourseMoveTracker,
    CoursePathTracker,
    CourseScoreTracker,
    CourseTracker,
    Node,
    NodePoints,
    NodePowerup,
)
from src.storage import ICacheRepository
from src.tasks.game import calc_node_points, initialize_course

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
    # get node neighbourhood as an adjacency list
    G: nx.Graph = resolver(request.app.state.compressor, True)
    cache_storage: ICacheRepository = request.app.state.cacheRepository
    course: CourseComplete = cache_storage.get_course(uid)
    modifiers: CourseModifiersHidden | None = cache_storage.get_course_modifiers(uid)
    if not modifiers:
        raise HTTPException(status_code=503, detail="Unexpected cache error")
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


@router.post("/move-into-node", response_model=CourseTracker)
async def move_into_node(request: Request, uid: str, target_node: Node):
    """Move into a node and return the updated course tracker"""
    raise HTTPException(status_code=501, detail="Not implemented")
