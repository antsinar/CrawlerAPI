import logging
import random
from functools import cached_property
from typing import Dict

import networkx as nx

from src.constants import SCORE_MULTIPLIER_INCREMENT, PowerupType, TrapType
from src.dependencies import GraphResolver
from src.models import (
    Course,
    CourseComplete,
    CourseModifiersHidden,
    CoursePowerup,
    CourseTracker,
    CourseTrap,
    Node,
)
from src.storage import ICacheRepository

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
        logger.info("inside task")
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
            logger.info("creating modifiers")
            [self.create_trap(node) for node in traps_sample]
            [self.create_powerup(node) for node in powerups_sample]
        except Exception as e:
            logger.error(e)
            return

        # set up random traps and powerups on the maximum distance available
        try:
            modifiers = CourseModifiersHidden(traps=self.traps, powerups=self.powerups)
            logger.info("saving modifiers")
            self.cache_storage.set_course_modifiers(self.course.uid, modifiers)
        except Exception as e:
            logger.error(f"Error saving modifiers in cache: {e}")
            return

        logger.info("modifiers ready")


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
    logger.info("entering task")
    if cache_storage.course_exists(course_id=course.uid):
        logger.error("course already saved")
        return
    try:
        cache_storage.set_course(course.uid, course)
    except Exception as e:
        logger.error(f"error in storing course in cache: {e}")
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


def calc_node_points(G: nx.Graph, start_node: str, neighbour: str) -> int:
    """calculate node points based on the distance from spawn
    Increase points by 10 for every hop required
    """
    path = nx.shortest_path(G, source=start_node, target=neighbour)
    if not path:
        return 0
    return (len(path) - 1) * 10


def calc_move_multiplier(tracker: CourseTracker, target_node: Node) -> float:
    return (
        tracker.score_tracker.multiplier + SCORE_MULTIPLIER_INCREMENT
        if target_node not in tracker.path_tracker.movement_path
        else 1.0
    )
