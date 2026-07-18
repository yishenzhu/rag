from fastapi import APIRouter, Depends
from ..core import EmbedReq, EmbedRsp
from ..rag import Pipeline

embedding_router = APIRouter(prefix="/embedding", tags=["嵌入服务"])


@embedding_router.post("", response_model=EmbedRsp, tags=["嵌入"])
def embed(req: EmbedReq, pipeline: Pipeline = Depends(Pipeline.get)):
    embeddings = pipeline._embedding.encode(req.texts)
    return EmbedRsp(
        embeddings=embeddings,
        count=len(embeddings),
        dimension=len(embeddings[0]) if len(embeddings) > 0 else 0,
    )
