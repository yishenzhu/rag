"""Embedding 微服务 —— 独立进程加载 BGE-M3 模型并提供 HTTP API"""

import torch
import numpy as np
import time
from FlagEmbedding import BGEM3FlagModel
from fastapi import FastAPI
from pydantic import BaseModel
import uvicorn
import argparse
import logging

logger = logging.getLogger(__name__)


# ── 请求/响应模型 ──────────────────────────────────────────────

class EmbedRequest(BaseModel):
    texts: list[str]
    hybrid: bool = False


class EmbedResponse(BaseModel):
    dense_vecs: list[list[float]]
    sparse_vectors: list[dict] | None = None
    count: int
    dimension: int


class DimsResponse(BaseModel):
    dims: int


# ── 服务主体 ────────────────────────────────────────────────────

def create_app(
    model_name: str = "BAAI/bge-m3",
    batch_size: int = 128,
    device: str | None = None,
) -> FastAPI:
    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"

    logger.info("Loading embedding model: %s on %s", model_name, device)
    t0 = time.perf_counter()
    model = BGEM3FlagModel(model_name, devices=device, batch_size=batch_size)
    elapsed = time.perf_counter() - t0
    dims = model.model.model.config.hidden_size
    logger.info("Embedding model loaded in %.1fs, dims=%d", elapsed, dims)

    app = FastAPI(title="Embedding Service", version="1.0.0")

    @app.post("/embed", response_model=EmbedResponse)
    async def embed(req: EmbedRequest):
        output = model.encode(
            req.texts, return_dense=True, return_sparse=req.hybrid
        )
        sparse = None
        if req.hybrid and output.get("lexical_weights"):
            sparse = [
                {
                    "indices": [int(k) for k in lw],
                    "values": [float(v) for v in lw.values()],
                }
                for lw in output["lexical_weights"]
            ]

        dense = output["dense_vecs"]
        if isinstance(dense, np.ndarray):
            dense = dense.tolist()

        return EmbedResponse(
            dense_vecs=dense,
            sparse_vectors=sparse,
            count=len(req.texts),
            dimension=dims,
        )

    @app.get("/dims", response_model=DimsResponse)
    async def get_dims():
        return DimsResponse(dims=dims)

    @app.get("/health")
    async def health():
        return {"status": "ok", "model": model_name, "device": device}

    return app


def main():
    parser = argparse.ArgumentParser(description="Embedding 微服务")
    parser.add_argument("--model", default="BAAI/bge-m3")
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8002)
    parser.add_argument("--device", default=None, help="cuda / cpu，默认自动检测")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    app = create_app(args.model, args.batch_size, args.device)
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
