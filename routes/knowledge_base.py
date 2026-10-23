from fastapi import APIRouter, Depends, Query

from ..core import (
    AppError,
    CreateCollectionRequest,
    CreateCollectionResponse,
    DeleteCollectionResponse,
    IngestRequest,
    IngestResponse,
    ListCollectionsResponse,
    SearchRequest,
    SearchResponse,
)
from ..engine import RAGPipeline

knowledge_router = APIRouter(prefix="/knowledge", tags=["知识库"])


@knowledge_router.get("", response_model=ListCollectionsResponse, tags=["知识库列表"])
async def list_collections(
    enabled: bool = Query(True, description="激活状态"),
    brief: bool = Query(True, description="简要信息"),
    include_inactive: bool = Query(False, description="包含向量模型不匹配的集合"),
    pipeline: RAGPipeline = Depends(RAGPipeline.from_request),
):
    collections = pipeline._knowledge.list_collections(
        enabled, brief, include_inactive=include_inactive
    )
    return ListCollectionsResponse(collections=collections, count=len(collections))


@knowledge_router.post("", response_model=CreateCollectionResponse, tags=["创建知识库表"])
async def create_collection(
    req: CreateCollectionRequest,
    pipeline: RAGPipeline = Depends(RAGPipeline.from_request),
):
    try:
        await pipeline._knowledge.create_collection(req.model_dump())
        return CreateCollectionResponse(collection=req.name, success=True)
    except AppError as e:
        return CreateCollectionResponse(collection=req.name, error_code=e.code)


@knowledge_router.delete("/{name}", response_model=DeleteCollectionResponse, tags=["删除知识库"])
async def delete_collection(
    name: str,
    pipeline: RAGPipeline = Depends(RAGPipeline.from_request),
):
    try:
        await pipeline._knowledge.delete_collection(name)
        return DeleteCollectionResponse(collection=name, success=True)
    except AppError as e:
        return DeleteCollectionResponse(collection=name, error_code=e.code)


@knowledge_router.post("/ingest", response_model=IngestResponse, tags=["知识库文档导入"])
async def ingest(
    req: IngestRequest,
    pipeline: RAGPipeline = Depends(RAGPipeline.from_request),
):
    try:
        await pipeline._knowledge.ingest_documents(
            req.collection, req.documents,
            req.chunk_size, req.chunk_overlap,
            chunker_type=req.chunker_type,
        )
        return IngestResponse(
            collection=req.collection, success=True, count=len(req.documents)
        )
    except AppError as e:
        return IngestResponse(collection=req.collection, error_code=e.code)


@knowledge_router.post("/search", response_model=SearchResponse, tags=["知识库搜索"])
async def search(
    req: SearchRequest,
    pipeline: RAGPipeline = Depends(RAGPipeline.from_request),
):
    try:
        results = await pipeline._knowledge.search_collection(
            req.collection,
            req.queries,
            top_k=req.top_k,
            threshold=req.threshold,
            search_type=req.search_type,
            rerank=req.rerank,
            filters=req.filters,
        )
        return SearchResponse(results=results, success=True)
    except AppError as e:
        return SearchResponse(results=[], error_code=e.code)

