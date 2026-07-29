from fastapi import APIRouter, Depends, Query
from ..engine import Pipeline
from ..core import (
    ListRsp,
    CreateReq,
    CreateRsp,
    IngestReq,
    IngestRsp,
    DeleteRsp,
    SearchReq,
    SearchRsp,
    AppError,
)

knowledge_router = APIRouter(prefix="/knowledge", tags=["知识库"])


@knowledge_router.get("", response_model=ListRsp, tags=["知识库列表"])
async def list_collections(
    enabled: bool = Query(True, description="激活状态"),
    brief: bool = Query(True, description="简要信息"),
    pipeline: Pipeline = Depends(Pipeline.get),
):
    collections = pipeline._knowledge.list_collections(enabled, brief)
    return ListRsp(collections=collections, count=len(collections))


@knowledge_router.post("", response_model=CreateRsp, tags=["创建知识库表"])
async def create_collection(req: CreateReq, pipeline: Pipeline = Depends(Pipeline.get)):
    try:
        await pipeline._knowledge.create(req.model_dump())
        return CreateRsp(collection=req.name, success=True)
    except AppError as e:
        return CreateRsp(collection=req.name, error_code=e.code)


@knowledge_router.delete("/{name}", response_model=DeleteRsp, tags=["删除知识库"])
async def delete_collection(name: str, pipeline: Pipeline = Depends(Pipeline.get)):
    try:
        await pipeline._knowledge.delete(name)
        return DeleteRsp(collection=name, success=True)
    except AppError as e:
        return DeleteRsp(collection=name, error_code=e.code)


@knowledge_router.post("/ingest", response_model=IngestRsp, tags=["知识库文档导入"])
async def ingest(req: IngestReq, pipeline: Pipeline = Depends(Pipeline.get)):
    try:
        await pipeline._knowledge.ingest(
            req.collection, req.documents,
            req.chunk_size, req.chunk_overlap,
            chunker_type=req.chunker_type,
        )
        return IngestRsp(
            collection=req.collection, success=True, count=len(req.documents)
        )
    except AppError as e:
        return IngestRsp(collection=req.collection, error_code=e.code)


@knowledge_router.post("/search", response_model=SearchRsp, tags=["知识库搜索"])
async def search(req: SearchReq, pipeline: Pipeline = Depends(Pipeline.get)):
    try:
        results = await pipeline._knowledge.search(
            req.collection,
            req.queries,
            top_k=req.top_k,
            threshold=req.threshold,
            search_type=req.search_type,
            rerank=req.rerank,
            filters=req.filters,
        )
        return SearchRsp(results=results, success=True)
    except AppError as e:
        return SearchRsp(results=[], error_code=e.code)

