"""向量化管道版本与集合 active 状态测试。"""

from types import SimpleNamespace

import httpx
import pytest
from rag.core import AppError, CollectionInfo, EmbeddingConfig, ErrorCode
from rag.embedding.client import EmbeddingClient
from rag.engine import collection as collection_module
from rag.engine.collection import VectorCollection
from rag.engine.knowledge_base import KnowledgeBase


class FakeEmbed:
    def __init__(self, dims: int = 2048, embedding_id: str = "qwen3vl-v1"):
        self._dims = dims
        self._configured_id = embedding_id
        self._embedding_id = ""
        self.calls = 0

    async def get_dims(self) -> int:
        self.calls += 1
        self._embedding_id = self._configured_id
        return self._dims

    @property
    def embedding_id(self) -> str:
        return self._embedding_id


class FakeStore:
    def __init__(self, dims: int = 2048, metadata: dict | None = None):
        self._dims = dims
        self._metadata = metadata or {}
        self.created: dict | None = None

    async def load_collection_info(self):
        return None

    @property
    def dims(self) -> int:
        return self._dims

    @property
    def metadata(self) -> dict:
        return self._metadata

    async def create(self, dims: int, metadata: dict | None = None):
        self.created = metadata
        self._dims = dims
        self._metadata = metadata or {}


def make_collection(
    monkeypatch, metadata: dict, dims: int = 2048, embed_dims: int = 2048
):
    store = FakeStore(dims=dims, metadata=metadata)
    monkeypatch.setattr(collection_module, "QdrantVectorStore", lambda name, client: store)
    collection = VectorCollection(
        "KnowledgeBase.test",
        FakeEmbed(embed_dims),
        object(),
    )
    return collection, store


def metadata(embedding_id: str = "qwen3vl-v1") -> dict:
    return {"name": "test", "embedding_id": embedding_id}


@pytest.mark.asyncio
async def test_active_when_embedding_id_and_dims_match(monkeypatch):
    collection, _ = make_collection(monkeypatch, metadata())

    assert await collection.check_compatibility() is True
    assert collection.active is True
    assert collection.get_info().embedding_id == "qwen3vl-v1"
    assert collection.get_info().inactive_reason is None


@pytest.mark.asyncio
async def test_legacy_collection_without_embedding_id_is_inactive(monkeypatch):
    collection, _ = make_collection(monkeypatch, {"name": "test"})

    assert await collection.check_compatibility() is False
    assert collection.active is False
    assert collection.get_info().inactive_reason == "missing embedding_id"


@pytest.mark.asyncio
async def test_embedding_id_mismatch_is_inactive(monkeypatch):
    collection, _ = make_collection(monkeypatch, metadata("bge-m3-v1"))
    embed = collection._embed

    assert await collection.check_compatibility() is False
    assert "embedding_id mismatch" in collection.get_info().inactive_reason
    assert embed.calls == 1


@pytest.mark.asyncio
async def test_dimension_mismatch_is_inactive(monkeypatch):
    collection, _ = make_collection(
        monkeypatch, metadata(), dims=1024, embed_dims=2048
    )

    assert await collection.check_compatibility() is False
    assert "embedding dims 2048 != collection dims 1024" == (
        collection.get_info().inactive_reason
    )


@pytest.mark.asyncio
async def test_initialize_keeps_service_alive_and_hides_inactive(monkeypatch):
    active = FakeStore(
        dims=2048, metadata={"name": "active", "embedding_id": "qwen3vl-v1"}
    )
    inactive = FakeStore(
        dims=1024, metadata={"name": "inactive", "embedding_id": "qwen3vl-v1"}
    )
    stores = {
        "KnowledgeBase.active": active,
        "KnowledgeBase.inactive": inactive,
    }
    monkeypatch.setattr(
        collection_module, "QdrantVectorStore", lambda name, client: stores[name]
    )
    registry = KnowledgeBase(FakeEmbed(), object(), None)

    await registry.load_collections(
        [
            SimpleNamespace(name="KnowledgeBase.active"),
            SimpleNamespace(name="KnowledgeBase.inactive"),
        ]
    )

    assert [c.name for c in registry.list_collections(True, False)] == ["active"]
    assert [c.name for c in registry.list_collections(True, False, True)] == [
        "active",
        "inactive",
    ]

    with pytest.raises(AppError) as exc:
        registry.get_collection("inactive")
    assert exc.value.code == ErrorCode.COLLECTION_INACTIVE


@pytest.mark.asyncio
async def test_create_stores_embedding_id_but_not_runtime_state(monkeypatch):
    store = FakeStore(dims=2048)
    monkeypatch.setattr(collection_module, "QdrantVectorStore", lambda name, client: store)
    registry = KnowledgeBase(FakeEmbed(), object(), None)

    await registry.create_collection({"name": "new"})

    assert store.created["embedding_id"] == "qwen3vl-v1"
    assert "active" not in store.created
    assert "inactive_reason" not in store.created
    assert registry.get_collection("new").active is True


@pytest.mark.asyncio
async def test_embedding_client_reads_id_from_dims_endpoint():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/dims"
        return httpx.Response(
            200, json={"dims": 2048, "embedding_id": "qwen3vl-v1"}
        )

    client = EmbeddingClient("http://embedding")
    client._client = httpx.AsyncClient(
        base_url="http://embedding", transport=httpx.MockTransport(handler)
    )
    try:
        assert await client.get_dims() == 2048
        assert client.embedding_id == "qwen3vl-v1"
    finally:
        await client.aclose()


def test_embedding_config_id_prefers_explicit_value():
    conf = EmbeddingConfig(
        id="qwen3vl-2b-int8-v1",
        model="models/Qwen3-VL-Embedding-2B",
        multimodal=True,
    )
    assert conf.embedding_id == "qwen3vl-2b-int8-v1"


def test_embedding_config_id_falls_back_to_model_name():
    conf = EmbeddingConfig(model="models/Qwen3-VL-Embedding-2B", multimodal=True)
    assert conf.embedding_id == "qwen3-vl-embedding-2b-mm"


def test_collection_info_runtime_fields_default_to_active():
    info = CollectionInfo.model_validate({"name": "test", "embedding_id": "v1"})
    assert info.active is True
    assert info.inactive_reason is None
