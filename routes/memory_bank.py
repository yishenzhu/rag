from fastapi import APIRouter, Depends

from ..core import (
    AppError,
    CreateCollectionRequest,
    CreateCollectionResponse,
)
from ..engine import RAGPipeline

memory_router = APIRouter(prefix="/memory", tags=["记忆库"])


@memory_router.post("", response_model=CreateCollectionResponse, tags=["创建记忆表"])
async def create_collection(
    req: CreateCollectionRequest,
    pipeline: RAGPipeline = Depends(RAGPipeline.from_request),
):
    try:
        await pipeline._memory.create_collection(req.model_dump())
        return CreateCollectionResponse(collection=req.name, success=True)
    except AppError as e:
        return CreateCollectionResponse(collection=req.name, error_code=e.code)
