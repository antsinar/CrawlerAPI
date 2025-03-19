from __future__ import annotations

import logging
from typing import Annotated, Callable, List
from urllib.parse import urlparse

import networkx as nx
from fastapi import APIRouter, Depends, Request

from src.constants import Compressor
from src.Graph.dependencies import get_crawled_urls, get_resolver, url_in_crawled
from src.Graph.models import GraphInfo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/graphs", tags=["graphs"])


@router.get("/all")
async def graphs(crawled_urls: Annotated[List[str], Depends(get_crawled_urls)]):
    """Return already crawled website graphs"""
    return {
        "crawled_urls": crawled_urls,
    }


@router.get("/", response_model=GraphInfo)
async def graph_info(
    request: Request,
    url: str,
    url_crawled: Annotated[None, Depends(url_in_crawled)],
    resolver: Annotated[Callable[[Compressor, bool], nx.Graph], Depends(get_resolver)],
):
    """Return graph information, if present"""
    try:
        return request.app.state.info_updater.graph_info[urlparse(url).netloc]
    except KeyError:
        logger.info("Computing graph info")
        G = resolver(request.app.state.compressor, True)
        return GraphInfo(num_nodes=G.number_of_nodes(), num_edges=G.number_of_edges())
