"""Usage flusher tests."""

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from rag.infrastructure.cache.usage_flush import UsageFlusher


class FakeRedis:
    def __init__(self, items):
        self.items = list(items)
        self.requeued = []

    async def lpop(self, key, count=None):
        if not self.items:
            return None
        batch, self.items = self.items[:count], self.items[count:]
        return batch

    async def lpush(self, key, *values):
        self.requeued = list(values)
        for value in values:
            self.items.insert(0, value)


class FakeSession:
    def __init__(self, fail=False):
        self.fail = fail
        self.committed = False

    async def execute(self, stmt):
        if self.fail:
            raise RuntimeError("db down")

    async def commit(self):
        self.committed = True


def event(metric="request"):
    return json.dumps(
        {
            "event_id": str(uuid4()),
            "tenant_id": str(uuid4()),
            "project_id": str(uuid4()),
            "api_key_id": None,
            "metric": metric,
            "quantity": 1,
            "period": "2026-10",
            "occurred_at": datetime.now(UTC).isoformat(),
        }
    )


@pytest.mark.asyncio
async def test_flush_drains_queue_and_commits():
    redis = FakeRedis([event(), event()])
    session = FakeSession()

    count = await UsageFlusher(redis, session, batch_size=10).flush()

    assert count == 2
    assert session.committed
    assert redis.items == []


@pytest.mark.asyncio
async def test_flush_requeues_on_db_failure():
    first, second = event("first"), event("second")
    redis = FakeRedis([first, second])
    session = FakeSession(fail=True)

    with pytest.raises(RuntimeError):
        await UsageFlusher(redis, session, batch_size=10).flush()

    assert redis.items == [first, second]
