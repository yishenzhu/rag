"""Memory route tests (fake session, no database)."""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from rag.app.deps import AuthPrincipal
from rag.app.memory_routes import CreateMemoryRequest, content_hash, create_memory
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
    def __init__(self, one=None, many=None):
        self.one, self.many = one, many
        self.added, self.committed = [], False

    async def execute(self, stmt):
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


@pytest.mark.asyncio
async def test_create_and_dedupe_memory():
    principal = make_principal()
    session = FakeSession()
    response = await create_memory(
        CreateMemoryRequest(content="hello", metadata={"topic": "x"}),
        principal,
        session,
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

    existing = make_record(content="hello", memory_metadata={"topic": "x"})
    deduped = await create_memory(
        CreateMemoryRequest(content="hello"), principal, FakeSession(one=existing)
    )
    assert deduped.id == existing.id
