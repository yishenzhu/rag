"""Memory vector index tests (fake embedding and Qdrant clients)."""

from types import SimpleNamespace
from uuid import UUID, uuid4

import numpy as np
import pytest
from rag.infrastructure.vector.memory_index import MemoryIndex


class FakeEmbedder:
    async def get_dims(self):
        return 3

    async def encode(self, texts, images=None, hybrid=False):
        return np.array([[0.1, 0.2, 0.3]] * len(texts), dtype=np.float32), None


class FakeQdrant:
    def __init__(self):
        self.created = None
        self.indexes = []
        self.points = []
        self.deleted = []
        self.query = None

    async def get_collections(self):
        return SimpleNamespace(collections=[])

    async def create_collection(self, collection_name, vectors_config):
        self.created = (collection_name, vectors_config)

    async def create_payload_index(self, collection_name, field_name, field_schema):
        self.indexes.append(field_name)

    async def upsert(self, collection_name, points):
        self.points.extend(points)

    async def delete(self, collection_name, points_selector):
        self.deleted.append(points_selector)

    async def query_points(
        self, collection_name, query, using, query_filter, limit, with_payload
    ):
        self.query = (query, using, limit)
        return SimpleNamespace(
            points=[
                SimpleNamespace(
                    payload={
                        "memory_id": "00000000-0000-0000-0000-000000000001",
                        "content": "hello",
                        "metadata": {"topic": "x"},
                    },
                    score=0.9,
                )
            ]
        )


def make_memory():
    return SimpleNamespace(
        id=uuid4(), tenant_id=uuid4(), project_id=uuid4(),
        content="hello", memory_metadata={"topic": "x"}, status="active",
    )


@pytest.mark.asyncio
async def test_initialize_index_and_delete():
    client = FakeQdrant()
    index = MemoryIndex(client, FakeEmbedder())
    await index.initialize()

    name, config = client.created
    assert name == "memories_v1"
    assert config["dense"].size == 3
    assert client.indexes == ["tenant_id", "project_id", "status"]

    memory = make_memory()
    await index.index(memory)
    point = client.points[0]
    assert point.id == str(memory.id)
    assert point.payload["tenant_id"] == str(memory.tenant_id)
    assert point.payload["project_id"] == str(memory.project_id)
    assert np.allclose(point.vector["dense"], [0.1, 0.2, 0.3])

    await index.delete(memory.id)
    assert client.deleted

    hits = await index.search(memory.tenant_id, memory.project_id, "hello", 5)
    assert hits[0].memory_id == UUID("00000000-0000-0000-0000-000000000001")
    assert hits[0].content == "hello"
    assert hits[0].score == 0.9
    assert client.query[1] == "dense"
