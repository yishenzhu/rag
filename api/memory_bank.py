from fastapi import APIRouter, Depends
from ..core import (
    CreateReq,
    CreateRsp,
    AddReq,
    AddRsp,
    SearchReq,
    SearchRsp,
    AppError,
)
from ..rag import Pipeline

memory_router = APIRouter(prefix="/memory", tags=["记忆库"])


@memory_router.post("", response_model=CreateRsp, tags=["创建记忆表"])
async def create_collection(req: CreateReq, pipeline: Pipeline = Depends(Pipeline.get)):
    try:
        await pipeline._memory.create(req.model_dump())
        return CreateRsp(collection=req.name, success=True)
    except AppError as e:
        return CreateRsp(collection=req.name, error_code=e.code)


@memory_router.post("/add", response_model=AddRsp, tags=["添加记忆"])
async def add(req: AddReq, pipeline: Pipeline = Depends(Pipeline.get)):
    try:
        await pipeline._memory.add(req.collection, req.memories, req.dup_threshold)
        return AddRsp(
            collection=req.collection,
            success=True,
            count=len(req.memories),
        )
    except AppError as e:
        return AddRsp(
            collection=req.collection,
            error_code=e.code,
        )


@memory_router.post("/search", response_model=SearchRsp, tags=["记忆库搜索"])
async def search(req: SearchReq, pipeline: Pipeline = Depends(Pipeline.get)):
    try:
        results = await pipeline._memory.search(
            req.collection, req.queries, req.top_k, req.threshold, req.search_type
        )
        return SearchRsp(
            collection=req.collection,
            queries=req.queries,
            results=results,
            count=len(results),
            success=True,
        )
    except AppError as e:
        return SearchRsp(
            collection=req.collection,
            queries=req.queries,
            error_code=e.code,
        )
