"""Qdrant-backed vector index for memories."""

from uuid import UUID

from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qdrant

from ...embedding import EmbeddingClient
from ..db.models import Memory

COLLECTION = "memories_v1"
VECTOR_NAME = "dense"


class MemoryIndex:
    def __init__(
        self,
        client: AsyncQdrantClient,
        embedder: EmbeddingClient,
        collection: str = COLLECTION,
    ) -> None:
        self.client = client
        self.embedder = embedder
        self.collection = collection

    async def initialize(self) -> None:
        dims = await self.embedder.get_dims()
        collections = await self.client.get_collections()
        if any(item.name == self.collection for item in collections.collections):
            return
        await self.client.create_collection(
            collection_name=self.collection,
            vectors_config={
                VECTOR_NAME: qdrant.VectorParams(
                    size=dims, distance=qdrant.Distance.COSINE
                )
            },
        )
        for field in ("tenant_id", "project_id", "status"):
            await self.client.create_payload_index(
                collection_name=self.collection,
                field_name=field,
                field_schema=qdrant.PayloadSchemaType.KEYWORD,
            )

    async def index(self, memory: Memory) -> None:
        dense, _ = await self.embedder.encode([memory.content])
        payload = {
            "memory_id": str(memory.id),
            "tenant_id": str(memory.tenant_id),
            "project_id": str(memory.project_id),
            "content": memory.content,
            "metadata": memory.memory_metadata,
            "status": memory.status,
        }
        await self.client.upsert(
            collection_name=self.collection,
            points=[
                qdrant.PointStruct(
                    id=str(memory.id),
                    vector={VECTOR_NAME: dense[0].tolist()},
                    payload=payload,
                )
            ],
        )

    async def delete(self, memory_id: UUID) -> None:
        await self.client.delete(
            collection_name=self.collection,
            points_selector=qdrant.PointIdsList(points=[str(memory_id)]),
        )
