import random
from typing import Annotated, Callable

import networkx as nx
from fastapi import APIRouter, Depends, HTTPException, Request

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
    Course,
    CourseMoveTracker,
    CoursePathTracker,
    CourseScoreTracker,
    CourseTracker,
    Node,
)

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
        if request.state.graph_info[url].num_nodes in difficulty_range
    ]
    random.shuffle(possible_urls)
    return {"url": random.choice(possible_urls)}


@router.post("/begin", response_model=CourseTracker)
async def course_begin(
    request: Request,
    url: str,
    url_crawled: Annotated[None, Depends(url_in_crawled)],
    resolver: Annotated[Callable[[Compressor, bool], nx.Graph], Depends(get_resolver)],
):
    """Initialize a tracker object for a playable course"""
    G = resolver(request.state.compressor, True)
    nodes_list = list(G.nodes)
    source = random.choice(nodes_list)
    course = Course(url=url, start_node=Node(id=source), end_node=None)
    return CourseTracker(
        course=course,
        move_tracker=CourseMoveTracker(),
        score_tracker=CourseScoreTracker(),
        path_tracker=CoursePathTracker(
            current_node=course.start_node,
            movement_path=[
                course.start_node,
            ],
        ),
    )


@router.get("/get-neighbourhood", response_model=AdjList)
async def get_node_neighbourhood(
    request: Request,
    uid: str,
    current_node: Node,
    resolver: Annotated[nx.Graph, Depends(resolve_graph_from_course)],
):
    raise HTTPException(status_code=501, detail="Not implemented")


@router.post("/move-into-node", response_model=CourseTracker)
async def move_into_node(request: Request, uid: str, target_node: Node):
    """Move into a node and return the updated course tracker"""
    raise HTTPException(status_code=501, detail="Not implemented")
