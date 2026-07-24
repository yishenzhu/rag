from fastapi import APIRouter, Depends
from ..core import (
    CreateReq,
    CreateRsp,
    AppError,
)
from ..engine import Pipeline

memory_router = APIRouter(prefix="/memory", tags=["记忆库"])


@memory_router.post("", response_model=CreateRsp, tags=["创建记忆表"])
async def create_collection(req: CreateReq, pipeline: Pipeline = Depends(Pipeline.get)):
    try:
        await pipeline._memory.create(req.model_dump())
        return CreateRsp(collection=req.name, success=True)
    except AppError as e:
        return CreateRsp(collection=req.name, error_code=e.code)
