"""Embedding 微服务 —— 独立进程加载模型并提供 HTTP API。

两个后端工厂，由 create_app 统一路由：
- bge_app：FlagEmbedding.BGEM3FlagModel，文本 + 稀疏（默认）
- qwen_vl_app：sentence-transformers 加载 Qwen3-VL-Embedding，文本 + 图片多模态
"""

import argparse
import logging
import time

import numpy as np
import torch
import uvicorn
from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

logger = logging.getLogger(__name__)


# ── 请求/响应模型 ──────────────────────────────────────────────


class EmbedRequest(BaseModel):
    texts: list[str] = []
    images: list[str] = []  # http(s) URL 或服务端本机图片路径，供多模态后端使用
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
    multimodal: bool = False,
) -> FastAPI:
    """按是否多模态路由：multimodal=True 时创建多模态 app。"""
    if multimodal:
        return qwen_vl_app(model_name, batch_size, device)
    return bge_app(model_name, batch_size, device)


def bge_app(
    model_name: str,
    batch_size: int,
    device: str | None,
) -> FastAPI:
    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"

    logger.info("Loading embedding model: %s on %s", model_name, device)
    t0 = time.perf_counter()
    from FlagEmbedding import BGEM3FlagModel

    model = BGEM3FlagModel(model_name, devices=device, batch_size=batch_size)
    elapsed = time.perf_counter() - t0
    dims = model.model.model.config.hidden_size
    logger.info("Embedding model loaded in %.1fs, dims=%d", elapsed, dims)

    app = FastAPI(title="Embedding Service", version="1.0.0")

    @app.post("/embed", response_model=EmbedResponse)
    async def embed(req: EmbedRequest):
        if not req.texts:
            return EmbedResponse(dense_vecs=[], count=0, dimension=dims)

        output = await run_in_threadpool(
            model.encode, req.texts, return_dense=True, return_sparse=req.hybrid
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


def qwen_vl_app(
    model_name: str,
    batch_size: int,
    device: str | None,
) -> FastAPI:
    """Qwen3-VL-Embedding 多模态后端：文本与图片（http(s) URL / 服务端本机 path）统一向量空间。"""
    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"

    logger.info(
        "Loading multimodal embedding model: %s on %s (int8)", model_name, device
    )
    t0 = time.perf_counter()
    from sentence_transformers import SentenceTransformer
    from transformers import BitsAndBytesConfig

    # 8bit 量化加载：权重显存占用减半，需 device_map 由 bnb 管理设备
    model = SentenceTransformer(
        model_name,
        trust_remote_code=True,
        device=device,
        model_kwargs={
            "quantization_config": BitsAndBytesConfig(load_in_8bit=True),
            "device_map": {"": device},
        },
    )
    # 用一次空文本前向探测输出维度（2048），同时触发权重加载
    probe = model.encode([""])
    dims = probe.shape[-1]
    elapsed = time.perf_counter() - t0
    logger.info("Multimodal model loaded in %.1fs, dims=%d", elapsed, dims)

    app = FastAPI(title="Multimodal Embedding Service", version="1.0.0")

    @app.post("/embed", response_model=EmbedResponse)
    async def embed(req: EmbedRequest):
        # hybrid 无意义：Qwen3-VL-Embedding 不产出稀疏向量，直接忽略
        if not req.texts and not req.images:
            return EmbedResponse(dense_vecs=[], count=0, dimension=dims)

        inputs: list[str | dict] = []
        inputs.extend(req.texts)  # 纯文本 str
        inputs.extend({"image": v} for v in req.images)

        embeddings = await run_in_threadpool(
            model.encode, inputs, batch_size=batch_size, normalize_embeddings=True
        )
        dense = np.asarray(embeddings, dtype=np.float32).tolist()
        return EmbedResponse(
            dense_vecs=dense,
            sparse_vectors=None,
            count=len(req.texts) + len(req.images),
            dimension=dims,
        )

    @app.get("/dims", response_model=DimsResponse)
    async def get_dims():
        return DimsResponse(dims=dims)

    @app.get("/health")
    async def health():
        return {
            "status": "ok",
            "model": model_name,
            "device": device,
            "multimodal": True,
        }

    return app


# ── 入口 ────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Embedding 微服务")
    parser.add_argument(
        "--conf",
        default="conf/conf.yaml",
        help="配置文件路径（默认 conf/conf.yaml），读取顶层 embedding 配置",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    from ..core import Config

    cfg = Config.load(args.conf).embedding
    app = create_app(cfg.model, cfg.batch_size, multimodal=cfg.multimodal)
    uvicorn.run(app, host=cfg.host, port=cfg.port)


if __name__ == "__main__":
    main()
