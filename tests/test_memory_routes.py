"""Memory route tests (fake session, no database)."""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from rag.app.deps import AuthPrincipal
from rag.app.memory_routes import (
    CreateMemoryRequest,
    UpdateMemoryRequest,
    content_hash,
    create_memory,
    delete_memory,
    get_memory,
    list_memories,
    update_memory,
)
from rag.infrastructure.db.models import Memory


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
        "external_id": None, "content": "hello", "memory_metadata": {},
        "status": "active", "source": "api", "importance": 0.5,
        "expires_at": None, "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class FakeIndex:
    def __init__(self):
        self.indexed = []

    async def index(self, memory):
        self.indexed.append(memory)


@pytest.mark.asyncio
async def test_create_and_dedupe_memory():
    principal = make_principal()
    session = FakeSession()
    index = FakeIndex()
    response = await create_memory(
        CreateMemoryRequest(content="hello", metadata={"topic": "x"}),
        principal,
        session,
        index,
    )

    memory = session.added[0]
    assert isinstance(memory, Memory)
    assert (memory.tenant_id, memory.project_id) == (
        principal.tenant_id, principal.project_id
    )
    assert memory.content_hash == content_hash("hello")
    assert (memory.memory_metadata, memory.status, memory.source) == (
        {"topic": "x"}, "active", "api"
    )
    assert response.id == memory.id and session.committed
    assert index.indexed == [memory]

    existing = make_record(content="hello", memory_metadata={"topic": "x"})
    deduped = await create_memory(
        CreateMemoryRequest(content="hello"),
        principal,
        FakeSession(one=existing),
        FakeIndex(),
    )
    assert deduped.id == existing.id


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
    assert session.committed

    other = make_record()
    conflict = FakeSession(results=[record, other])
    with pytest.raises(HTTPException) as exc:
        await update_memory(
            record.id, UpdateMemoryRequest(content="other"), principal, conflict
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

    with pytest.raises(HTTPException) as exc:
        await delete_memory(uuid4(), principal, FakeSession(one=None))
    assert exc.value.status_code == 404
