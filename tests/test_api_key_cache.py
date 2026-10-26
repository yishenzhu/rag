"""API key cache tests."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from rag.infrastructure.cache.api_keys import ApiKeyCache, CachedApiKey
from redis.exceptions import RedisError


class FakeRedis:
    def __init__(self):
        self.data = {}

    async def get(self, key):
        return self.data.get(key)

    async def set(self, key, value, ex=None):
        self.data[key] = value

    async def delete(self, key):
        self.data.pop(key, None)


class FailingRedis:
    async def get(self, key):
        raise RedisError("down")

    async def set(self, key, value, ex=None):
        raise RedisError("down")

    async def delete(self, key):
        raise RedisError("down")


def make_record(**overrides):
    values = {
        "id": uuid4(), "tenant_id": uuid4(), "project_id": uuid4(),
        "key_prefix": "sk_live_abc", "key_hash": "hash",
        "scopes": ["memories:read"], "status": "active",
        "expires_at": None, "revoked_at": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.asyncio
async def test_cache_roundtrip_and_delete():
    redis = FakeRedis()
    cache = ApiKeyCache(redis)
    record = make_record()
    await cache.set(record)
    cached = await cache.get(record.key_prefix)

    assert isinstance(cached, CachedApiKey)
    assert (cached.id, cached.tenant_id, cached.scopes) == (
        record.id, record.tenant_id, record.scopes
    )
    await cache.delete(record.key_prefix)
    assert await cache.get(record.key_prefix) is None


@pytest.mark.asyncio
async def test_cache_fail_open():
    cache = ApiKeyCache(FailingRedis())
    assert await cache.get("missing") is None
    await cache.set(make_record())
    await cache.delete("missing")
