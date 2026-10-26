"""Idempotency store tests."""

import pytest
from rag.infrastructure.cache.idempotency import IdempotencyStore
from redis.exceptions import RedisError


class FakeRedis:
    def __init__(self): self.data = {}
    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.data: return None
        self.data[key] = value
        return True
    async def get(self, key): return self.data.get(key)
    async def delete(self, key): self.data.pop(key, None)


class FailingRedis:
    async def set(self, *args, **kwargs): raise RedisError("down")
    async def get(self, key): raise RedisError("down")
    async def delete(self, key): raise RedisError("down")


@pytest.mark.asyncio
async def test_claim_states():
    store = IdempotencyStore(FakeRedis())
    assert await store.claim("scope", "k", "hash1") == "claimed"
    assert await store.claim("scope", "k", "hash1") == "in_progress"
    await store.complete("scope", "k", "hash1")
    assert await store.claim("scope", "k", "hash1") == "duplicate"
    assert await store.claim("scope", "k", "hash2") == "reused"
    await store.release("scope", "k")
    assert await store.claim("scope", "k", "hash2") == "claimed"


@pytest.mark.asyncio
async def test_fail_open():
    store = IdempotencyStore(FailingRedis())
    assert await store.claim("scope", "k", "hash") == "claimed"
    await store.complete("scope", "k", "hash")
    await store.release("scope", "k")
