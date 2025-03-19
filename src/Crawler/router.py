from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.exceptions import HTTPException
from fastapi.responses import JSONResponse

from src.Crawler.models import QueueUrl
from src.dependencies import url_not_in_crawled_from_object, validate_url

router = APIRouter(prefix="/crawl", tags=["crawler"])


@router.post("/queue-website/")
async def queue_website(
    request: Request,
    queue_url: QueueUrl,
    url_valid: Annotated[None, Depends(validate_url)],
    url_crawled: Annotated[None, Depends(url_not_in_crawled_from_object)],
):
    """Append website for crawling and return status"""
    if not url_crawled and queue_url.force:
        raise HTTPException(status_code=409, detail="Already Crawled")
    await request.app.state.task_queue.push_url(queue_url.url)
    return JSONResponse(
        status_code=201,
        content={
            "message": "Queued for Crawling",
            "position": request.app.state.task_queue.get_size(),
        },
    )


@router.get("/status")
async def get_status(request: Request):
    return await request.app.state.task_queue.get_status()
