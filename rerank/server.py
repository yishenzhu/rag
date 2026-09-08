"""Rerank 微服务 —— 独立进程加载 CrossEncoder 模型并提供 HTTP API。

按 multimodal 配置加载两类 CrossEncoder：
- 传统文本 rerank（ms-marco / bge-reranker）
- Qwen3-VL-Reranker：文本 + 图片多模态，int8 量化加载
"""

import argparse
import logging
import time

import torch
import uvicorn
from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sentence_transformers import CrossEncoder

logger = logging.getLogger(__name__)


# ── 请求/响应模型 ──────────────────────────────────────────────


class RerankRequest(BaseModel):
    queries: list[str]
    texts: list[list[str]] = []  # 每个 query 的文本文档列表
    images: list[list[str]] = []  # 每个 query 的图片文档（http(s) URL / 本机 path），排在文本之后


class RerankResponse(BaseModel):
    scores: list[list[float]]


# ── 服务主体 ────────────────────────────────────────────────────


def create_app(
    model_name: str = "cross-encoder/ms-marco-MiniLM-L6-v2",
    batch_size: int = 256,
    device: str | None = None,
    multimodal: bool = False,
) -> FastAPI:
    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"

    load_kwargs: dict = {}
    if multimodal:
        from transformers import BitsAndBytesConfig

        logger.info("Loading multimodal rerank model: %s on %s (int8)", model_name, device)
        load_kwargs = {
            "trust_remote_code": True,
            "model_kwargs": {
                "quantization_config": BitsAndBytesConfig(load_in_8bit=True),
                "device_map": {"": device},
            },
        }
    else:
        logger.info("Loading rerank model: %s on %s", model_name, device)
        load_kwargs = {"device": device, "max_length": 512}

    t0 = time.perf_counter()
    model = CrossEncoder(model_name, **load_kwargs)
    elapsed = time.perf_counter() - t0
    logger.info("Rerank model loaded in %.1fs", elapsed)

    app = FastAPI(title="Rerank Service", version="1.0.0")

    @app.post("/rerank", response_model=RerankResponse)
    async def rerank(req: RerankRequest):
        pairs: list = []
        for q, ts, ims in zip(req.queries, req.texts, req.images):
            for t in ts:
                pairs.append((q, t))
            for im in ims:
                if not multimodal:
                    raise ValueError("纯文本 rerank 模型不支持图片输入（images 需配 Qwen3-VL-Reranker）")
                pairs.append((q, {"image": im}))

        if not pairs:
            return RerankResponse(scores=[[] for _ in req.queries])

        t0 = time.perf_counter()
        flat = await run_in_threadpool(model.predict, pairs, batch_size=batch_size)
        elapsed = time.perf_counter() - t0
        logger.info("Reranked %d pairs across %d queries in %.3fs", len(pairs), len(req.queries), elapsed)

        scores = []
        idx = 0
        for ts, ims in zip(req.texts, req.images):
            n = len(ts) + len(ims)
            scores.append([float(v) for v in flat[idx : idx + n]])
            idx += n
        return RerankResponse(scores=scores)

    @app.get("/health")
    async def health():
        return {"status": "ok", "model": model_name, "device": device, "multimodal": multimodal}

    return app


# ── 入口 ────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Rerank 微服务")
    parser.add_argument(
        "--conf", default="conf/conf.yaml", help="配置文件路径（默认 conf/conf.yaml），读取顶层 rerank 配置"
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    from ..core import Config

    cfg = Config.load(args.conf).rerank
    app = create_app(cfg.model, cfg.batch_size, multimodal=cfg.multimodal)
    uvicorn.run(app, host=cfg.host, port=cfg.port)


if __name__ == "__main__":
    main()
