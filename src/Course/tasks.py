import logging
import random
from datetime import datetime
from functools import cached_property
from typing import Dict, List

import networkx as nx

from src.constants import SCORE_MULTIPLIER_INCREMENT, PowerupType, TrapType
from src.Course.models import (
    Course,
    CourseComplete,
    CourseModifiersHidden,
    CoursePowerup,
    CourseTracker,
    CourseTrap,
)
from src.Graph.dependencies import GraphResolver
from src.Graph.models import Node
from src.Leaderboard.models import LeaderboardComplete, LeaderboardDisplay
from src.Stores.interfaces import ICacheRepository, ILeaderboardRepository

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class CourseModHandler:
    def __init__(
        self,
        course: Course,
        graph: nx.Graph,
        cache_storage: ICacheRepository,
        num_traps: int = 0,
        num_powerups: int = 0,
    ):
        self.course = course
        self.cache_storage = cache_storage
        self.graph = graph
        self.num_traps = num_traps
        self.num_powerups = num_powerups
        self.traps: Dict[str, CourseTrap] = dict()
        self.powerups: Dict[str, CoursePowerup] = dict()

    @cached_property
    def resolver(self) -> GraphResolver:
        return GraphResolver(self.course.url)

    def create_trap(self, node_id: str) -> None:
        self.traps[node_id] = CourseTrap(type=random.choice(list(TrapType)))

    def create_powerup(self, node_id: str) -> None:
        self.powerups[node_id] = CoursePowerup(type=random.choice(list(PowerupType)))

    def initialize_modifiers(self, graph: nx.Graph) -> None:
        target_distance = 3
        try:
            furthest_nodes = [
                node
                for node in graph.nodes()
                if nx.shortest_path_length(graph, self.course.start_node.id, node)
                >= target_distance
            ]
            traps_sample = random.sample(furthest_nodes, self.num_traps)
            powerups_sample = random.sample(
                sorted(set(furthest_nodes).difference(traps_sample)), self.num_powerups
            )
        except nx.NetworkXError as e:
            logger.error(f"Graph error: {e}")
            return

        try:
            [self.create_trap(node) for node in traps_sample]
            [self.create_powerup(node) for node in powerups_sample]
        except Exception as e:
            logger.error(e)
            return

        try:
            modifiers = CourseModifiersHidden(traps=self.traps, powerups=self.powerups)
            self.cache_storage.set_course_modifiers(self.course.uid, modifiers)
        except Exception as e:
            logger.error(f"Error saving modifiers in cache: {e}")
            return

        logger.info("Course Modifiers ready")


def initialize_course(
    course: CourseComplete,
    graph: nx.Graph,
    cache_storage: ICacheRepository,
    num_traps: int = 0,
    num_powerups: int = 0,
) -> None:
    """Store object containing information about the course
    and initialize the powerup creation class
    """
    if cache_storage.course_exists(course_id=course.uid):
        logger.error("Course already saved")
        return
    try:
        cache_storage.set_course(course.uid, course)
    except Exception as e:
        logger.error(f"Error in storing course in cache: {e}")
        return
    mod_handler = CourseModHandler(
        Course(
            uid=course.uid,
            url=course.url,
            start_node=course.start_node,
            end_node=course.end_node,
        ),
        graph=graph,
        cache_storage=cache_storage,
        num_traps=num_traps,
        num_powerups=num_powerups,
    )

    mod_handler.initialize_modifiers(graph)


def calc_node_points(
    G: nx.Graph, start_node: str, neighbour: str, teleport_nodes: List[str] = list()
) -> int:
    """calculate node points based on the distance from spawn
    Increase points by 10 for every hop required
    """
    path = nx.shortest_path(G, source=start_node, target=neighbour)
    if not path:
        return 0
    if neighbour in teleport_nodes:
        return 0
    return (len(path) - 1) * 10


def calc_move_multiplier(
    tracker: CourseTracker, target_node: Node, teleport_nodes: List[str] = list()
) -> float:
    if target_node.id in teleport_nodes:
        return tracker.score_tracker.multiplier
    return (
        tracker.score_tracker.multiplier + SCORE_MULTIPLIER_INCREMENT
        if target_node not in tracker.path_tracker.movement_path
        else 1.0
    )


def write_to_leaderboard(
    leaderboard_handler: ILeaderboardRepository, course: CourseComplete
) -> None:
    logger.info("Initializing leaderboard")
    try:
        leaderboard_handler.init_leaderboard(
            course.url, course.tracker.move_tracker.moves_target.value
        )
        tracker_uid = leaderboard_handler.write_tracker_object(
            LeaderboardComplete(**course.model_dump())
        )

        if not tracker_uid:
            return

        leaderboard_handler.update_leaderboard(
            course.url,
            course.tracker.move_tracker.moves_target.value,
            LeaderboardDisplay(
                nickname=course.nickname,
                score=course.tracker.score_tracker.points,
                course_uid=course.uid,
                stamp=datetime.strftime(datetime.now(), "%H:%M:%S @ %d/%m/%Y"),
            ),
            tracker_uid,
        )
    except Exception as e:
        logger.error(f"Error in updating leaderboard: {e}")
        return
    logger.info("Updated leaderboard successfully")
