from pydantic import BaseModel
import yaml
from pathlib import Path
import logging

BASE_DIR = Path(__file__).resolve().parent.parent


def auto_path(path: str):
    p = Path(path)
    if not p.is_absolute():
        p = BASE_DIR / p
    return str(p.resolve())


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8001


class EmbeddingConfig(BaseModel):
    model: str = "BAAI/bge-m3"
    batch_size: int = 32
    server: str = "http://localhost:8002"


class RerankConfig(BaseModel):
    model: str = "BAAI/bge-reranker-v2-m3"
    batch_size: int = 32
    server: str = "http://localhost:8003"


class VectorStoreConfig(BaseModel):
    host: str = "localhost"
    port: int = 6333


class RAGConfig(BaseModel):
    qdrant: VectorStoreConfig
    embedding: EmbeddingConfig
    rerank: RerankConfig


class LogConfig(BaseModel):
    level: str
    path: str
    backup_count: int

    @property
    def level_int(self) -> int:
        return getattr(logging, self.level.upper(), logging.INFO)


class Config(BaseModel):
    app: ServerConfig
    rag: RAGConfig
    log: LogConfig
    mcp: ServerConfig

    @classmethod
    def load(cls, path: str = "conf/conf.yaml"):
        with open(auto_path(path), encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return cls.model_validate(data)
