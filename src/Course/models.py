from __future__ import annotations

import random
from enum import Enum
from typing import Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field, PositiveInt

from src.constants import MoveOptions, PowerupType, TrapType
from src.Graph.models import Node


class NodePoints(Node):
    points: int = Field(default=10)


class NodeInCourse(BaseModel):
    uid: str
    node: Node


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

    points: float = Field(default=0.0)
    multiplier: float = Field(default=1.0)


class CoursePathTracker(BaseModel):
    """Maintain track of player movement throughout the play session"""

    current_node: Node
    movement_path: List[Node]
    teleport_nodes_used: List[Node] = Field(default_factory=list)


class CourseTrap(BaseModel):
    type: TrapType = Field(default_factory=lambda _: random.choice(list(TrapType)))
    moves_left: int = Field(default=10)


class CoursePowerup(BaseModel):
    type: PowerupType = Field(
        default_factory=lambda _: random.choice(list(PowerupType))
    )
    moves_left: int = Field(default=10)


class NodePowerup(Node):
    powerup: CoursePowerup


class AdjListPoints(BaseModel):
    source: NodePoints
    dest: List[NodePoints | NodePowerup]


class CourseModifiersTracker(BaseModel):
    """Wrapper object for course modifiers"""

    triggered_traps: List[CourseTrap] = Field(default_factory=list)
    active_powerups: List[CoursePowerup] = Field(default_factory=list)


class CourseModifiersHidden(CourseModifiersTracker):
    """Object generated in course setup, contains all stored course modifiers"""

    traps: Dict[str, CourseTrap]
    powerups: Dict[str, CoursePowerup]


class CourseTracker(BaseModel):
    """Wrapper object for course trackers"""

    move_tracker: CourseMoveTracker
    score_tracker: CourseScoreTracker
    path_tracker: CoursePathTracker
    modifiers_tracker: CourseModifiersTracker


class GameState(Enum):
    IN_PROGRESS = 0
    FINISHED = 1


class CourseComplete(Course):
    """Wrapper around course object to contain all user relevant information"""

    nickname: str = Field(
        default_factory=lambda _: "".join(
            [chr(random.randrange(65, 90)) for _ in range(5)]
        )
    )
    game_state: GameState = Field(default=GameState.IN_PROGRESS)
    tracker: CourseTracker
