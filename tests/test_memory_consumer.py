"""Memory consumer tests (fake session and index)."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from rag.infrastructure.queue.consumer import MemoryConsumer


class FakeSession:
    def __init__(self, memory):
        self.memory, self.committed = memory, False
    async def get(self, model, memory_id): return self.memory
    async def commit(self): self.committed = True
    async def rollback(self): pass


class FakeIndex:
    def __init__(self):
        self.indexed, self.deleted = [], []
        self.indexed_status = []
    async def index(self, memory):
        self.indexed.append(memory)
        self.indexed_status.append(memory.status)
    async def delete(self, memory_id): self.deleted.append(memory_id)


def make_memory(**overrides):
    values = {
        "id": uuid4(), "tenant_id": uuid4(), "project_id": uuid4(),
        "status": "pending", "qdrant_point_id": None, "updated_at": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def make_event(memory, event_type="memory.created"):
    return {
        "event_type": event_type,
        "payload": {
            "memory_id": str(memory.id),
            "tenant_id": str(memory.tenant_id),
            "project_id": str(memory.project_id),
        },
    }


@pytest.mark.asyncio
async def test_ingest_marks_memory_active():
    memory = make_memory()
    index, session = FakeIndex(), FakeSession(memory)
    await MemoryConsumer(session, index).handle(make_event(memory))

    assert index.indexed == [memory]
    assert index.indexed_status == ["active"]
    assert (memory.status, memory.qdrant_point_id) == ("active", memory.id)
    assert memory.updated_at is not None and session.committed


@pytest.mark.asyncio
async def test_delete_event_removes_vector():
    memory = make_memory(status="deleted")
    index, session = FakeIndex(), FakeSession(memory)
    await MemoryConsumer(session, index).handle(
        make_event(memory, "memory.deleted")
    )
    assert index.deleted == [memory.id] and session.committed


@pytest.mark.asyncio
async def test_ignores_missing_or_foreign_memory():
    missing = make_memory()
    missing_index, missing_session = FakeIndex(), FakeSession(None)
    await MemoryConsumer(missing_session, missing_index).handle(
        make_event(missing)
    )
    assert not missing_index.indexed and not missing_session.committed

    memory = make_memory()
    foreign = make_event(memory)
    foreign["payload"]["tenant_id"] = str(uuid4())
    foreign_index, foreign_session = FakeIndex(), FakeSession(memory)
    await MemoryConsumer(foreign_session, foreign_index).handle(foreign)
    assert not foreign_index.indexed and not foreign_session.committed
