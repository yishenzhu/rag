"""Token bucket rate limiter tests."""

import pytest
from rag.infrastructure.cache.rate_limit import RateLimiter
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
async def test_allow_and_deny():
    redis = FakeRedis(results=[[1, 9], [0, 0]])
    limiter = RateLimiter(redis, rate=10, burst=20)

    assert await limiter.allow("key:1") == (True, 9)
    assert await limiter.allow("key:1") == (False, 0)

    numkeys, args = redis.calls[0]
    assert numkeys == 1
    assert args[0] == "rl:key:1"
    assert args[1:] == (10, 20, 1)


@pytest.mark.asyncio
async def test_fail_open():
    limiter = RateLimiter(FakeRedis(fail=True), rate=10, burst=20)
    assert await limiter.allow("key:1") == (True, 20)
