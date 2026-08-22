from qdrant_client import AsyncQdrantClient
from typing import Any
import asyncio
import logging
from ..embedding import EmbeddingClient
from ..vector_store import VectorStore
from ..rerank import RerankClient
from ..core import (
    Text,
    CollectionInfo,
    CollectionBriefInfo,
    SearchResult,
    SearchType,
    AppError,
    ErrorCode,
)

logger = logging.getLogger(__name__)


class Collection:
    def __init__(
        self,
        collection_name: str,
        embed_client: EmbeddingClient,
        store_client: AsyncQdrantClient,
        rerank_client: RerankClient | None = None,
    ):
        self._embed = embed_client
        self._rerank = rerank_client
        self._store = VectorStore(
            name=collection_name,
            client=store_client,
        )

    async def validate(self):
        await self._store.connect()
        dims = await self._embed.get_dims()
        if dims != self._store.dims:
            raise ValueError(
                f"Embedding dims {dims} does not match collection dims {self._store.dims}"
            )
        self._info = CollectionInfo.model_validate(self._store.metadata)
        return self

    @property
    def enabled(self):
        return self._info.enabled

    @property
    def hybrid(self):
        return self._info.hybrid

    def info(self, brief=False) -> CollectionInfo | CollectionBriefInfo:
        return (
            self._info
            if not brief
            else CollectionBriefInfo.model_validate(self._info.model_dump())
        )

    async def setup(self, info: CollectionInfo):
        dims = await self._embed.get_dims()
        await self._store.create(dims, info.model_dump())
        self._info = info
        return self

    async def encode(self, texts: list[Text]):
        return await self._embed.encode([t.content for t in texts], self.hybrid)

    async def insert(self, texts: list[Text], dup_threshold: float | None = None):
        payloads = [text.model_dump() for text in texts]
        ids = [text.hash_id for text in texts]

        dense_vectors, sparse_vectors = await self.encode(texts)

        await self._store.insert(
            payloads, ids, dense_vectors, sparse_vectors, dup_threshold
        )

    async def search(
        self,
        queries: list[str],
        top_k: int,
        threshold: float,
        search_type: SearchType,
        rerank: bool = False,
        filters: dict[str, Any] | None = None,
    ) -> list[SearchResult]:

        hybrid = search_type == SearchType.HYBRID and self.hybrid
        do_rerank = rerank and self._rerank is not None

        dense_vectors, sparse_vectors = await self._embed.encode(queries, hybrid)

        # 一次 batch 检索全部 query，返回 per-query 结果
        points_list = await self._store.query(
            dense_vectors,
            top_k * 2 if do_rerank else top_k,
            threshold,
            filters,
            sparse_vectors if sparse_vectors else None,
        )

        # 先解析全部结果
        all_results = [
            [SearchResult(payload=Text.model_validate(p.payload), score=p.score) for p in points_list[i]]
            for i in range(len(queries))
        ]

        # batch rerank 全部 query，一次网络调用
        if do_rerank:
            texts = [[r.payload.content for r in results] for results in all_results]
            scores = await self._rerank.rerank(queries, texts)
            for i in range(len(queries)):
                # 按 rerank 分数排序并更新 score 字段
                ranked = sorted(zip(scores[i], all_results[i]), key=lambda x: x[0], reverse=True)
                all_results[i] = [
                    SearchResult(payload=r.payload, score=s)
                    for s, r in ranked
                ]

        # 合并去重：各 query 已在 [:top_k] 截断，按 hash_id 去重
        return list({r.payload.hash_id: r for results in all_results for r in results[:top_k]}.values())


class Registry:
    def __init__(
        self,
        embed_client: EmbeddingClient,
        store_client: AsyncQdrantClient,
        rerank_client: RerankClient | None = None,
    ):
        self._embed = embed_client
        self._store = store_client
        self._rerank = rerank_client
        self._collections: dict[str, Collection] = {}

    @classmethod
    def namespaced(cls, name: str) -> str:
        return f"{cls.__name__}.{name}"

    def collection(self, name: str, check_enabled: bool = True) -> Collection:
        collection = self._collections.get(self.__class__.namespaced(name))
        if not collection:
            raise AppError(ErrorCode.COLLECTION_NOT_FOUND)

        if check_enabled and not collection.enabled:
            raise AppError(ErrorCode.COLLECTION_DISABLED)

        return collection

    async def search(
        self,
        name: str,
        queries: list[str],
        top_k: int = 5,
        threshold: float = 0.1,
        search_type: SearchType = SearchType.DENSE,
        rerank: bool = False,
        filters: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        collection = self.collection(name)
        return await collection.search(
            queries, top_k, threshold, search_type, rerank, filters
        )

    async def search_all(
        self,
        queries: list[str],
        top_k: int = 5,
        threshold: float = 0.1,
        search_type: SearchType = SearchType.DENSE,
        rerank: bool = False,
    ) -> list[SearchResult]:
        enabled = [c for c in self._collections.values() if c.enabled]
        if not enabled:
            return []

        tasks = [
            c.search(
                queries,
                top_k,
                threshold,
                search_type,
                rerank=rerank,
            )
            for c in enabled
        ]
        batches = await asyncio.gather(*tasks)
        # 各 collection 已去重并截断，跨 collection 仅按 hash_id 去重
        results = list({r.payload.hash_id: r for batch in batches for r in batch}.values())

        return results

    async def initialize(self, collections: list):
        for collection in collections:
            name = collection.name
            if name.startswith(self.__class__.namespaced("")):
                self._collections[name] = Collection(
                    name, self._embed, self._store, self._rerank
                )

        await asyncio.gather(*[c.validate() for c in self._collections.values()])

    def list_collections(
        self, check_enabled: bool, brief: bool
    ) -> list[CollectionInfo | CollectionBriefInfo]:
        return [
            c.info(brief)
            for c in self._collections.values()
            if not check_enabled or c.enabled
        ]

    async def create(self, metadata: dict[str, Any]):
        info = CollectionInfo.model_validate(metadata)

        collection_name = self.__class__.namespaced(info.name)
        if collection_name in self._collections:
            raise AppError(ErrorCode.COLLECTION_EXISTS)

        self._collections[collection_name] = await Collection(
            collection_name, self._embed, self._store, self._rerank
        ).setup(info)

        logger.info(f"Created collection {collection_name}")

    async def delete(self, name: str):
        collection_name = self.__class__.namespaced(name)
        if collection_name not in self._collections:
            raise AppError(ErrorCode.COLLECTION_NOT_FOUND)

        del self._collections[collection_name]
        await self._store.delete_collection(collection_name)

        logger.info(f"Deleted collection {collection_name}")
