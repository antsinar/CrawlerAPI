from pydantic import BaseModel


class QueueUrl(BaseModel):
    url: str
    force: bool = False
