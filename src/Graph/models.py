from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field


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
    teleport_nodes: List[Node] = Field(default_factory=list)


class NodeInGraph(BaseModel):
    url: str
    node: Node

    def __str__(self):
        return f"{self.url}: {self.node}"
