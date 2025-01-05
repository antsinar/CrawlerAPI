from functools import cached_property
from typing import List, Optional

from pydantic import BaseModel


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


class QueueUrl(BaseModel):
    url: str
    force: bool = False


class NodeInGraph(BaseModel):
    url: str
    node: Node

    def __str__(self):
        return f"{self.url}: {self.node}"


class Course(BaseModel):
    url: str
    start_node: Node
    end_node: Optional[Node]

    @cached_property
    def course_seed(self):
        """Generate a unique seed for the course based on the url and start and end nodes
        FIXME: Temporary
        """
        return f"{self.url}:{self.start_node.id}->{self.end_node.id}"

    class Config:
        arbitrary_types_allowed = True
