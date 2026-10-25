import asyncio
from typing import Self

from fastapi import FastAPI, Request
from qdrant_client import AsyncQdrantClient

from ..core import RAGConfig
from ..embedding import EmbeddingClient
from ..rerank import RerankClient
from .knowledge_base import KnowledgeBase
from .memory_bank import MemoryBank


class RAGPipeline:
    def __init__(self, conf: RAGConfig):
        self._conf = conf
        self._store = AsyncQdrantClient(host=conf.qdrant.host, port=conf.qdrant.port)
        self._embedding = EmbeddingClient(conf.embedding.server)
        self._reranker = RerankClient(conf.rerank.server)
        self._memory = MemoryBank(self._embedding, self._store, self._reranker)
        self._knowledge = KnowledgeBase(self._embedding, self._store, self._reranker)

    async def initialize(self):
        collections = await self._store.get_collections()
        await asyncio.gather(
            self._memory.load_collections(collections.collections),
            self._knowledge.load_collections(collections.collections),
        )

        return self

    def bind_app(self, app: FastAPI):
        app.state.pipeline = self
        return self

    @property
    def store(self) -> AsyncQdrantClient:
        return self._store

    @property
    def embedding(self) -> EmbeddingClient:
        return self._embedding

    async def close(self):
        await asyncio.gather(
            self._embedding.aclose(),
            self._reranker.aclose(),
        )

    @classmethod
    def from_request(cls, request: Request) -> Self | None:
        pipeline = request.app.state.pipeline
        return pipeline if isinstance(pipeline, cls) else None
