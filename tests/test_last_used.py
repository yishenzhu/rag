"""last_used buffering tests."""

from uuid import uuid4

import pytest
from rag.infrastructure.cache.last_used import LastUsedFlusher
from redis.exceptions import RedisError


class FakeRedis:
    def __init__(self, data=None, fail=False):
        self.data = data or {}
        self.fail = fail
        self.deleted = []

    async def hgetall(self, key):
        if self.fail:
            raise RedisError("down")
        return self.data

    async def hdel(self, key, *fields):
        self.deleted.extend(fields)
        for field in fields:
            self.data.pop(field, None)


class FakeSession:
    def __init__(self):
        self.executed = False
        self.committed = False

    async def execute(self, stmt):
        self.executed = True

    async def commit(self):
        self.committed = True


@pytest.mark.asyncio
async def test_flush_updates_and_clears():
    ids = [uuid4(), uuid4()]
    redis = FakeRedis({str(item): "1" for item in ids})
    session = FakeSession()
    count = await LastUsedFlusher(redis, session).flush()

    assert count == 2
    assert session.executed and session.committed
    assert redis.deleted == [str(item) for item in ids]
    assert redis.data == {}


@pytest.mark.asyncio
async def test_flush_empty_and_fail_open():
    session = FakeSession()
    assert await LastUsedFlusher(FakeRedis(), session).flush() == 0
    assert not session.committed
    assert await LastUsedFlusher(FakeRedis(fail=True), session).flush() == 0
