"""Expose the v2 workflow through synchronous HTTP and SSE routes."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from .config import ResearchConfig
from .factory import build_research_loop
from .loop import ResearchLoop
from .serialization import serialize_task

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/research/v2", tags=["Research v2"])


class ResearchRequest(BaseModel):
    """Validate the topic and optional search backend override."""

    topic: str = Field(..., min_length=1, max_length=4000)
    search_api: Literal[
        "advanced", "duckduckgo", "serpapi", "tavily", "perplexity", "searxng"
    ] | None = None

    @field_validator("topic")
    @classmethod
    def validate_topic(cls, value: str) -> str:
        """Reject whitespace before beginning a streaming response."""
        value = value.strip()
        if not value:
            raise ValueError("请输入研究主题")
        return value


class ResearchResponse(BaseModel):
    """Return the final report and task snapshots."""

    report_markdown: str
    tasks: list[dict[str, object]]


def _build_loop(payload: ResearchRequest) -> ResearchLoop:
    overrides = {}
    if payload.search_api is not None:
        # v2 configuration takes environment-style keys.
        overrides["SEARCH_API"] = payload.search_api
    try:
        return build_research_loop(ResearchConfig.from_env(overrides))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to initialize research v2")
        raise HTTPException(status_code=500, detail="研究服务初始化失败，请查看后端日志") from exc


@router.post("", response_model=ResearchResponse)
def run_research(payload: ResearchRequest) -> ResearchResponse:
    """Run research to completion and return structured results."""
    loop = _build_loop(payload)
    try:
        result = loop.run(payload.topic)
        return ResearchResponse(
            report_markdown=result.report,
            tasks=[serialize_task(task) for task in result.state.tasks],
        )
    except Exception as exc:
        logger.exception("Research v2 failed")
        raise HTTPException(status_code=500, detail="研究执行失败，请查看后端日志") from exc


@router.post("/stream")
def stream_research(payload: ResearchRequest) -> StreamingResponse:
    """Forward stage events as SSE without blocking the ASGI event loop."""
    loop = _build_loop(payload)

    def event_iterator() -> Iterator[str]:
        try:
            for event in loop.run_stream(payload.topic):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception:
            logger.exception("Streaming research v2 failed")
            error = {"type": "error", "detail": "研究执行失败，请查看后端日志"}
            yield f"data: {json.dumps(error, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_iterator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
