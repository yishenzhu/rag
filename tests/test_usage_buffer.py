"""Usage buffer tests."""

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from rag.infrastructure.cache.usage_buffer import UsageBuffer
from rag.infrastructure.cache.usage_flush import UsageFlusher
from redis.exceptions import RedisError


class FakeRedis:
    def __init__(self, items=None, fail=False):
        self.items = list(items or [])
        self.fail = fail

    async def rpush(self, key, value):
        if self.fail:
            raise RedisError("down")
        self.items.append(value)

    async def lpop(self, key, count=None):
        if self.fail:
            raise RedisError("down")
        if not self.items:
            return None
        batch, self.items = self.items[:count], self.items[count:]
        return batch

    async def lpush(self, key, *values):
        for value in values:
            self.items.insert(0, value)


class FakeSession:
    def __init__(self): self.executed = self.committed = False
    async def execute(self, stmt): self.executed = True
    async def commit(self): self.committed = True


def make_event(**overrides):
    values = {
        "event_id": str(uuid4()), "tenant_id": str(uuid4()),
        "project_id": str(uuid4()), "api_key_id": None,
        "metric": "request", "quantity": 1, "period": "2026-10",
        "occurred_at": datetime.now(UTC).isoformat(),
    }
    values.update(overrides)
    return json.dumps(values)


@pytest.mark.asyncio
async def test_buffer_add():
    redis = FakeRedis()
    tenant, project, key_id = uuid4(), uuid4(), uuid4()
    await UsageBuffer(redis).add(tenant, project, key_id, "request")

    event = json.loads(redis.items[0])
    assert (event["metric"], event["quantity"]) == ("request", 1)
    assert (event["tenant_id"], event["project_id"]) == (str(tenant), str(project))
    assert len(event["period"]) == 7


@pytest.mark.asyncio
async def test_flush_batch():
    redis = FakeRedis([make_event(), make_event()])
    session = FakeSession()
    assert await UsageFlusher(redis, session).flush() == 2
    assert session.executed and session.committed and redis.items == []


@pytest.mark.asyncio
async def test_buffer_and_flush_fail_open():
    session = FakeSession()
    assert await UsageFlusher(FakeRedis(fail=True), session).flush() == 0
    assert not session.committed
    await UsageBuffer(FakeRedis(fail=True)).add(uuid4(), uuid4(), None, "request")
