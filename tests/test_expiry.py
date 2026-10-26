"""Memory expiry tests."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from rag.infrastructure.db.expiry import expire_memories


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return self

    def all(self):
        return self.rows


class FakeSession:
    def __init__(self, rows):
        self.rows = rows
        self.added = []
        self.committed = False

    async def execute(self, statement):
        return FakeResult(self.rows)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.committed = True


def make_memory(expires_at):
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        project_id=uuid4(),
        content_hash="hash",
        status="active",
        expires_at=expires_at,
        deleted_at=None,
        updated_at=None,
    )


@pytest.mark.asyncio
async def test_expire_marks_memory_and_enqueues_delete():
    now = datetime.now(UTC)
    memory = make_memory(now - timedelta(minutes=1))
    session = FakeSession([memory])

    assert await expire_memories(session, now=now) == 1

    assert memory.status == "expired"
    assert memory.deleted_at == now
    assert session.committed
    assert len(session.added) == 1
    assert session.added[0].event_type == "memory.deleted"
    assert session.added[0].topic == "memory.delete.v1"


@pytest.mark.asyncio
async def test_expire_nothing_does_not_commit():
    session = FakeSession([])

    assert await expire_memories(session) == 0
    assert not session.committed
    assert not session.added
