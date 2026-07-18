from qdrant_client import AsyncQdrantClient
import asyncio
from fastapi import FastAPI, Request
from pydantic import Field
from ..core import (
    RAGConfig,
    SearchResult,
    CollectionInfo,
    CollectionBriefInfo,
)
from ..embedding import EmbeddingClient
from ..rerank import RerankClient
from .knowledge_base import KnowledgeBase
from .memory_bank import MemoryBank


class Pipeline:
    def __init__(self, conf: RAGConfig):
        self._conf = conf
        self._store = AsyncQdrantClient(host=conf.qdrant.host, port=conf.qdrant.port)
        self._embedding = EmbeddingClient(conf.embedding)
        self._reranker = RerankClient(conf.rerank)
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

    async def add_user_memory(
        self, memories: list[str] = Field(description="要添加的记忆")
    ) -> bool:
        """添加用户记忆，当用户明确要求记住或对话中暴露用户重要信息时使用"""
        await self._memory.add("user", memories)
        return True

    async def search_user_memory(
        self, queries: list[str] = Field(description="要搜索的记忆")
    ) -> list[SearchResult]:
        """搜索用户记忆"""
        return await self._memory.search("user", queries, rerank=True)

    def list_knowledge_bases(self) -> list[CollectionInfo | CollectionBriefInfo]:
        """知识库列表"""
        return self._knowledge.list_collections(True, True)

    async def search_knowledge_base(
        self,
        collection: str = Field(description="知识库名，参考知识库列表"),
        queries: list[str] = Field(description="要搜索的相关内容"),
    ) -> list[SearchResult]:
        """知识库搜索"""
        return await self._knowledge.search(collection, queries)
