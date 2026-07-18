import torch
import numpy as np
import time
import logging
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from pydantic import BaseModel, Field
from FlagEmbedding import BGEM3FlagModel
from sentence_transformers import CrossEncoder

logger = logging.getLogger(__name__)


class EncodeReq(BaseModel):
    texts: list[str] = Field(description="要编码的文本列表")
    hybrid: bool = Field(
        default=False, description="是否同时返回稀疏向量 (用于混合检索)"
    )


class EncodeRsp(BaseModel):
    dense_vectors: list[list[float]]
    sparse_vectors: list[dict] | None = None
    count: int
    dimension: int


class RerankReq(BaseModel):
    query: str = Field(description="查询文本")
    texts: list[str] = Field(description="待排序的文档列表")


class RerankRsp(BaseModel):
    scores: list[float]


@asynccontextmanager
async def lifespan(app: FastAPI):
    device = "cuda" if torch.cuda.is_available() else "cpu"
    logger.info(f"Loading models on {device}...")

    logger.info("  Loading BGE-M3 embedding model...")
    app.state.embedding = BGEM3FlagModel(
        "BAAI/bge-m3",
        devices=device,
        batch_size=32,
    )
    logger.info(
        f"  BGE-M3 loaded, dims={app.state.embedding.model.model.config.hidden_size}"
    )

    logger.info("  Loading CrossEncoder rerank model...")
    app.state.rerank = CrossEncoder(
        "BAAI/bge-reranker-v2-m3",
        device=device,
        max_length=512,
        model_kwargs={"torch_dtype": torch.float16},
    )
    logger.info("  CrossEncoder loaded")

    logger.info("Model service ready")
    yield
    logger.info("Model service shutting down")


app = FastAPI(title="RAG Model Service", lifespan=lifespan)


@app.post("/encode", response_model=EncodeRsp)
async def encode(req: EncodeReq, request: Request):
    model = request.app.state.embedding
    output = model.encode(req.texts, return_dense=True, return_sparse=req.hybrid)

    dense = output["dense_vecs"]
    if isinstance(dense, np.ndarray):
        dense = dense.tolist()

    sparse = None
    if req.hybrid and "lexical_weights" in output:
        sparse = [
            {
                "indices": [int(k) for k in lw],
                "values": [float(v) for v in lw.values()],
            }
            for lw in output["lexical_weights"]
        ]

    return EncodeRsp(
        dense_vectors=dense,
        sparse_vectors=sparse,
        count=len(req.texts),
        dimension=model.model.model.config.hidden_size,
    )


@app.post("/rerank", response_model=RerankRsp)
async def rerank(req: RerankReq, request: Request):
    model = request.app.state.rerank
    pairs = [(req.query, doc) for doc in req.texts]

    t0 = time.perf_counter()
    scores = model.predict(pairs, batch_size=32).tolist()
    elapsed = time.perf_counter() - t0

    logger.info("Reranked %d docs in %.3fs", len(req.texts), elapsed)
    return RerankRsp(scores=scores)


@app.get("/health")
async def health(request: Request):
    return {
        "status": "ok",
        "has_embedding": hasattr(request.app.state, "embedding"),
        "has_rerank": hasattr(request.app.state, "rerank"),
    }


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    uvicorn.run(app, host="0.0.0.0", port=8000)
