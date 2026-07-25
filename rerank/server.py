"""Rerank 微服务 —— 独立进程加载 Cross-Encoder 模型并提供 HTTP API"""

import torch
from sentence_transformers import CrossEncoder
from fastapi import FastAPI
from pydantic import BaseModel
import uvicorn
import argparse
import time
import logging

logger = logging.getLogger(__name__)


# ── 请求/响应模型 ──────────────────────────────────────────────

class RerankRequest(BaseModel):
    query: str
    texts: list[str]


class RerankResponse(BaseModel):
    scores: list[float]
    count: int


# ── 服务主体 ────────────────────────────────────────────────────

def create_app(
    model_name: str = "cross-encoder/ms-marco-MiniLM-L6-v2",
    batch_size: int = 256,
    device: str | None = None,
) -> FastAPI:
    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"

    logger.info("Loading rerank model: %s on %s", model_name, device)
    t0 = time.perf_counter()
    model = CrossEncoder(
        model_name,
        device=device,
        max_length=512,
    )
    elapsed = time.perf_counter() - t0
    logger.info("Rerank model loaded in %.1fs", elapsed)

    app = FastAPI(title="Rerank Service", version="1.0.0")

    @app.post("/rerank", response_model=RerankResponse)
    async def rerank(req: RerankRequest):
        pairs = [(req.query, doc) for doc in req.texts]
        t0 = time.perf_counter()
        scores = model.predict(pairs, batch_size=batch_size).tolist()
        elapsed = time.perf_counter() - t0
        logger.info("Reranked %d docs in %.3fs", len(req.texts), elapsed)
        return RerankResponse(scores=scores, count=len(scores))

    @app.get("/health")
    async def health():
        return {"status": "ok", "model": model_name, "device": device}

    return app


def main():
    parser = argparse.ArgumentParser(description="Rerank 微服务")
    parser.add_argument(
        "--model", default="cross-encoder/ms-marco-MiniLM-L6-v2"
    )
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8003)
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
