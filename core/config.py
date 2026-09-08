import logging
from pathlib import Path

import yaml
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parent.parent


def auto_path(path: str):
    p = Path(path)
    if not p.is_absolute():
        p = BASE_DIR / p
    return str(p.resolve())


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8001


# ── 顶层模型服务配置（供模型服务进程启动） ───────────────────


class EmbeddingConfig(BaseModel):
    """embedding 服务进程启动配置（conf.yaml 顶层 embedding 块）。
    device 不配置：有 GPU 用 GPU，否则 CPU。"""

    model: str = "BAAI/bge-m3"
    batch_size: int = 32
    host: str = "0.0.0.0"
    port: int = 8002
    multimodal: bool = False


class RerankConfig(BaseModel):
    model: str = "BAAI/bge-reranker-v2-m3"
    batch_size: int = 32
    host: str = "0.0.0.0"
    port: int = 8003


# ── rag 块（应用连接配置，供 Pipeline 用） ─────────────────────


class EndpointRef(BaseModel):
    """客户端连接端点：host + port（与 qdrant 同构），server 为派生完整地址。"""

    host: str
    port: int

    @property
    def server(self) -> str:
        return f"http://{self.host}:{self.port}"


class VectorStoreConfig(BaseModel):
    host: str = "localhost"
    port: int = 6333


class RAGConfig(BaseModel):
    qdrant: VectorStoreConfig
    embedding: EndpointRef
    rerank: EndpointRef


class LogConfig(BaseModel):
    level: str
    path: str
    backup_count: int

    @property
    def level_int(self) -> int:
        return getattr(logging, self.level.upper(), logging.INFO)


class Config(BaseModel):
    app: ServerConfig
    embedding: EmbeddingConfig
    rerank: RerankConfig
    rag: RAGConfig
    log: LogConfig
    mcp: ServerConfig

    @classmethod
    def load(cls, path: str = "conf/conf.yaml"):
        with open(auto_path(path), encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return cls.model_validate(data)
