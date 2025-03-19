from typing import List

from pydantic import BaseModel


class QueueUrl(BaseModel):
    url: str
    force: bool = False


class Node(BaseModel):
    id: str

    def __str__(self):
        return self.id


class AdjList(BaseModel):
    source: Node
    dest: List[Node]

    def __str__(self):
        return f"{self.source} -> {self.dest}"
