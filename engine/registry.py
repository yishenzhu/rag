import logging
from typing import Any

from qdrant_client import AsyncQdrantClient

from ..core import (
    AppError,
    CollectionInfo,
    CollectionSummary,
    ErrorCode,
    FilterRule,
    SearchResult,
    SearchType,
)
from ..embedding import EmbeddingClient
from ..rerank import RerankClient
from .collection import VectorCollection

logger = logging.getLogger(__name__)


class CollectionRegistry:
    def __init__(
        self,
        embed_client: EmbeddingClient,
        store_client: AsyncQdrantClient,
        rerank_client: RerankClient | None = None,
    ):
        self._embed = embed_client
        self._store = store_client
        self._rerank = rerank_client
        self._collections: dict[str, VectorCollection] = {}

    @classmethod
    def namespaced_name(cls, name: str) -> str:
        return f"{cls.__name__}.{name}"

    def get_collection(self, name: str, check_enabled: bool = True) -> VectorCollection:
        collection = self._collections.get(self.__class__.namespaced_name(name))
        if not collection:
            raise AppError(ErrorCode.COLLECTION_NOT_FOUND)

        if check_enabled and not collection.enabled:
            raise AppError(ErrorCode.COLLECTION_DISABLED)
        if check_enabled and not collection.active:
            raise AppError(ErrorCode.COLLECTION_INACTIVE)

        return collection

    async def search_collection(
        self,
        name: str,
        queries: list[str],
        top_k: int = 5,
        threshold: float = 0.1,
        search_type: SearchType = SearchType.DENSE,
        rerank: bool = False,
        filters: list[FilterRule] | None = None,
    ) -> list[SearchResult]:
        collection = self.get_collection(name)
        return await collection.search(
            queries, top_k, threshold, search_type, rerank, filters
        )

    async def load_collections(self, collections: list):
        for collection in collections:
            name = collection.name
            if name.startswith(self.__class__.namespaced_name("")):
                self._collections[name] = VectorCollection(
                    name, self._embed, self._store, self._rerank
                )

        for collection in self._collections.values():
            await collection.check_compatibility()

    def list_collections(
        self, check_enabled: bool, brief: bool, include_inactive: bool = False
    ) -> list[CollectionInfo | CollectionSummary]:
        return [
            c.get_info(brief)
            for c in self._collections.values()
            if (not check_enabled or c.enabled)
            and (include_inactive or c.active)
        ]

    async def create_collection(self, metadata: dict[str, Any]):
        info = CollectionInfo.model_validate(metadata)

        collection_name = self.__class__.namespaced_name(info.name)
        if collection_name in self._collections:
            raise AppError(ErrorCode.COLLECTION_EXISTS)

        self._collections[collection_name] = await VectorCollection(
            collection_name, self._embed, self._store, self._rerank
        ).create(info)

        logger.info(f"Created collection {collection_name}")

    async def delete_collection(self, name: str):
        collection_name = self.__class__.namespaced_name(name)
        if collection_name not in self._collections:
            raise AppError(ErrorCode.COLLECTION_NOT_FOUND)

        del self._collections[collection_name]
        await self._store.delete_collection(collection_name)

        logger.info(f"Deleted collection {collection_name}")
