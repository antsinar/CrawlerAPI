import random
from typing import List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field, PositiveFloat, PositiveInt

from .constants import MoveOptions


class Node(BaseModel):
    id: str

    def __str__(self):
        return self.id


class AdjList(BaseModel):
    source: Node
    dest: List[Node]

    def __str__(self):
        return f"{self.source} -> {self.dest}"


class GraphInfo(BaseModel):
    num_nodes: int
    num_edges: int
    teleport_nodes: List[Node]


class QueueUrl(BaseModel):
    url: str
    force: bool = False


class NodeInGraph(BaseModel):
    url: str
    node: Node

    def __str__(self):
        return f"{self.url}: {self.node}"


class Course(BaseModel):
    uid: str = Field(default_factory=lambda _: uuid4().hex)
    url: str
    start_node: Node
    end_node: Optional[Node]


class CourseMoveTracker(BaseModel):
    moves_target: MoveOptions = Field(
        default_factory=lambda _: random.choice(list(MoveOptions))
    )
    moves_taken: PositiveInt = Field(default=0)


class CourseScoreTracker(BaseModel):
    """Maintain track of points scored throughout the user play session"""

    points: PositiveInt = Field(default=0)
    multiplier: PositiveFloat = Field(default=1.0, decimal_places=2)


class CoursePathTracker(BaseModel):
    """Maintain track of player movement throughout the play session"""

    movement_path: List[Node]
    teleport_nodes_used: List[Node] = Field(default_factory=list)


class CourseTracker(BaseModel):
    """Wrapper object for course trackers"""

    course: Course
    move_tracker: CourseMoveTracker
    score_tracker: CourseScoreTracker
    path_tracker: CoursePathTracker
