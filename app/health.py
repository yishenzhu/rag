"""Liveness and readiness endpoints, mounted at root and under /v1."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..engine import RAGPipeline

router = APIRouter(tags=["health"])


@router.get("/health/live")
async def live() -> dict[str, str]:
    return {"status": "ok", "service": "rag-api", "version": "v1"}


@router.get("/health/ready")
async def ready(request: Request):
    if RAGPipeline.from_request(request) is None:
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "reason": "pipeline_not_initialized"},
        )
    return {"status": "ok", "service": "rag-api"}
