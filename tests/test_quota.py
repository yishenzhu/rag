"""Monthly quota tests."""

from uuid import uuid4

import pytest
from rag.infrastructure.cache.quota import QuotaLimiter
from redis.exceptions import RedisError


class FakeRedis:
    def __init__(self, results=None, fail=False):
        self.results = list(results or [])
        self.fail = fail
        self.calls = []

    async def eval(self, script, numkeys, *args):
        if self.fail:
            raise RedisError("down")
        self.calls.append((numkeys, args))
        return self.results.pop(0)


@pytest.mark.asyncio
async def test_quota_allow_and_deny():
    tenant = uuid4()
    redis = FakeRedis(results=[[1, 5], [0, 100]])
    quota = QuotaLimiter(redis, limit=100)

    assert await quota.consume(tenant) == (True, 5)
    assert await quota.consume(tenant) == (False, 100)

    numkeys, args = redis.calls[0]
    assert numkeys == 1
    assert args[0].startswith(f"quota:{tenant}:")
    assert args[0].endswith(":requests")
    assert args[1:] == (100, 1, 3456000)


@pytest.mark.asyncio
async def test_quota_fail_open():
    quota = QuotaLimiter(FakeRedis(fail=True), limit=100)
    assert await quota.consume(uuid4()) == (True, 0)
