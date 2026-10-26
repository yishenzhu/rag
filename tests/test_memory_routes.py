"""Memory route tests (fake session, no database)."""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from rag.app.deps import AuthPrincipal
from rag.app.memory_routes import (
    CreateMemoryRequest,
    SearchMemoriesRequest,
    UpdateMemoryRequest,
    content_hash,
    create_memory,
    delete_memory,
    get_memory,
    list_memories,
    search_memories,
    update_memory,
)
from rag.infrastructure.db.models import Memory, OutboxEvent
from rag.infrastructure.vector.memory_index import MemoryHit


class FakeResult:
    def __init__(self, one=None, many=None):
        self.one, self.many = one, many or []

    def scalar_one_or_none(self):
        return self.one

    def scalars(self):
        return self

    def all(self):
        return self.many


class FakeSession:
    def __init__(self, one=None, many=None, results=None):
        self.one, self.many = one, many
        self.results = list(results or [])
        self.added, self.committed = [], False

    async def execute(self, stmt):
        if self.results:
            return FakeResult(self.results.pop(0))
        return FakeResult(self.one, self.many)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.committed = True

    async def rollback(self):
        pass


def make_principal(scopes=("memories:read", "memories:write")):
    return AuthPrincipal(uuid4(), uuid4(), uuid4(), scopes)


def make_record(**overrides):
    values = {
        "id": uuid4(), "tenant_id": uuid4(), "project_id": uuid4(),
        "external_id": None, "content": "hello",
        "content_hash": content_hash("hello"), "memory_metadata": {},
        "status": "active", "source": "api", "importance": 0.5,
        "expires_at": None, "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def outbox_events(session):
    return [obj for obj in session.added if isinstance(obj, OutboxEvent)]


class FakeIndex:
    def __init__(self):
        self.hits = []

    async def search(self, tenant_id, project_id, query, top_k):
        return self.hits


class FakeRedis:
    def __init__(self): self.data = {}
    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.data:
            return None
        self.data[key] = value
        return True
    async def get(self, key): return self.data.get(key)
    async def delete(self, key): self.data.pop(key, None)


@pytest.mark.asyncio
async def test_create_and_dedupe_memory():
    principal = make_principal()
    session = FakeSession()
    response = await create_memory(
        CreateMemoryRequest(content="hello", metadata={"topic": "x"}),
        principal,
        session,
    )

    memory = next(obj for obj in session.added if isinstance(obj, Memory))
    assert (memory.tenant_id, memory.project_id) == (
        principal.tenant_id, principal.project_id
    )
    assert memory.content_hash == content_hash("hello")
    assert (memory.memory_metadata, memory.status, memory.source) == (
        {"topic": "x"}, "pending", "api"
    )
    assert response.id == memory.id and session.committed

    events = outbox_events(session)
    assert len(events) == 1
    assert (events[0].event_type, events[0].topic) == (
        "memory.created", "memory.ingest.v1"
    )
    assert events[0].payload["memory_id"] == str(memory.id)

    existing = make_record(content="hello", memory_metadata={"topic": "x"})
    dedup_session = FakeSession(one=existing)
    deduped = await create_memory(
        CreateMemoryRequest(content="hello"), principal, dedup_session
    )
    assert deduped.id == existing.id
    assert not dedup_session.added


@pytest.mark.asyncio
async def test_list_and_get_memory():
    principal = make_principal()
    record = make_record(
        tenant_id=principal.tenant_id, project_id=principal.project_id
    )
    listed = await list_memories(principal, FakeSession(many=[record]), 20, 0)
    assert [item.id for item in listed] == [record.id]

    fetched = await get_memory(record.id, principal, FakeSession(one=record))
    assert fetched.id == record.id

    with pytest.raises(HTTPException) as exc:
        await get_memory(uuid4(), principal, FakeSession(one=None))
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_update_memory():
    principal = make_principal()
    record = make_record(
        tenant_id=principal.tenant_id, project_id=principal.project_id
    )
    session = FakeSession(results=[record, None])
    response = await update_memory(
        record.id,
        UpdateMemoryRequest(content="new content", metadata={"a": 1}),
        principal,
        session,
    )

    assert response.content == "new content"
    assert record.content_hash == content_hash("new content")
    assert record.memory_metadata == {"a": 1}
    assert record.status == "pending"
    assert session.committed

    events = outbox_events(session)
    assert events[0].event_type == "memory.updated"

    other = make_record()
    conflict = FakeSession(results=[record, other])
    with pytest.raises(HTTPException) as exc:
        await update_memory(
            record.id,
            UpdateMemoryRequest(content="other"),
            principal,
            conflict,
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_delete_memory():
    principal = make_principal()
    record = make_record(
        tenant_id=principal.tenant_id, project_id=principal.project_id
    )
    session = FakeSession(one=record)
    await delete_memory(record.id, principal, session)

    assert record.status == "deleted" and record.deleted_at is not None
    assert session.committed

    events = outbox_events(session)
    assert (events[0].event_type, events[0].topic) == (
        "memory.deleted", "memory.delete.v1"
    )

    with pytest.raises(HTTPException) as exc:
        await delete_memory(uuid4(), principal, FakeSession(one=None))
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_search_memories():
    principal = make_principal()
    hit = MemoryHit(uuid4(), "hello", {"topic": "x"}, 0.9)
    index = FakeIndex()
    index.hits = [hit]

    results = await search_memories(
        SearchMemoriesRequest(query="hello", top_k=5), principal, index
    )
    assert (results[0].id, results[0].content, results[0].score) == (
        hit.memory_id, hit.content, hit.score
    )


@pytest.mark.asyncio
async def test_create_memory_idempotency():
    principal = make_principal()
    redis = FakeRedis()
    request = CreateMemoryRequest(content="hello", metadata={"topic": "x"})

    first = await create_memory(
        request, principal, FakeSession(), redis=redis, idempotency_key="k1"
    )
    assert first.id
    with pytest.raises(HTTPException) as exc:
        await create_memory(
            request, principal, FakeSession(), redis=redis, idempotency_key="k1"
        )
    assert exc.value.status_code == 409
