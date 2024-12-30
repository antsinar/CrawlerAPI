from typing import List

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
