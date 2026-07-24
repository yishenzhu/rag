from qdrant_client import AsyncQdrantClient
import asyncio
from fastapi import FastAPI, Request
from ..core import (
    RAGConfig,
)
from ..embedding import EmbeddingClient
from ..rerank import RerankClient
from .knowledge_base import KnowledgeBase
from .memory_bank import MemoryBank


class Pipeline:
    def __init__(self, conf: RAGConfig):
        self._conf = conf
        self._store = AsyncQdrantClient(host=conf.qdrant.host, port=conf.qdrant.port)
        self._embedding = EmbeddingClient(conf.embedding.server)
        self._reranker = RerankClient(conf.rerank.server)
        self._memory = MemoryBank(self._embedding, self._store, self._reranker)
        self._knowledge = KnowledgeBase(self._embedding, self._store, self._reranker)

    async def setup(self):
        collections = await self._store.get_collections()
        await asyncio.gather(
            self._memory.initialize(collections.collections),
            self._knowledge.initialize(collections.collections),
        )

        return self

    def attach(self, app: FastAPI):
        app.state.pipeline = self
        return self

    @classmethod
    def get(cls, request: Request) -> "Pipeline":
        return request.app.state.pipeline
