"""API key auth dependency tests (fake repository, no database)."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from rag.app.deps import AuthPrincipal, require_api_key, require_scope
from rag.app.middleware import RequestContext, context, get_context
from rag.conf import get_settings
from rag.infrastructure.cache.api_keys import ApiKeyCache
from rag.security.api_keys import generate_api_key

PEPPER = get_settings().api_key_pepper


def make_request(token):
    headers = {} if token is None else {"authorization": f"Bearer {token}"}
    return SimpleNamespace(headers=headers)


def make_record(material, **overrides):
    values = {
        "id": uuid4(), "tenant_id": uuid4(), "project_id": uuid4(),
        "key_prefix": material.key_prefix, "key_hash": material.key_hash,
        "scopes": ["memories:read"], "status": "active",
        "revoked_at": None, "expires_at": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class FakeApiKeyRepository:
    def __init__(self, record):
        self.record = record

    async def get_by_prefix(self, key_prefix):
        if self.record and self.record.key_prefix == key_prefix:
            return self.record
        return None


async def authenticate(token, record):
    return await require_api_key(
        make_request(token), FakeApiKeyRepository(record), None
    )


class CacheRedis:
    def __init__(self): self.data = {}
    async def get(self, key): return self.data.get(key)
    async def set(self, key, value, ex=None): self.data[key] = value


class NoDatabase:
    async def get_by_prefix(self, key_prefix): raise AssertionError("db lookup should be skipped")


@pytest.mark.asyncio
async def test_require_api_key_uses_cache():
    material = generate_api_key(PEPPER)
    record = make_record(material)
    redis = CacheRedis()
    await ApiKeyCache(redis).set(record)
    principal = await require_api_key(make_request(material.plaintext), NoDatabase(), redis)
    assert principal.api_key_id == record.id


@pytest.mark.asyncio
async def test_require_api_key_populates_context():
    material = generate_api_key(PEPPER)
    record = make_record(material)
    token = context.set(RequestContext(request_id="req-test"))
    try:
        principal = await authenticate(material.plaintext, record)
        ctx = get_context()
    finally:
        context.reset(token)

    assert principal == AuthPrincipal(
        record.id, record.tenant_id, record.project_id, ("memories:read",)
    )
    assert (ctx.request_id, ctx.tenant_id, ctx.project_id) == (
        "req-test", str(record.tenant_id), str(record.project_id)
    )
    assert (ctx.actor_type, ctx.actor_id, ctx.scopes) == (
        "api_key", str(record.id), ("memories:read",)
    )


@pytest.mark.asyncio
async def test_rejects_invalid_keys():
    material = generate_api_key(PEPPER)
    expired = make_record(
        material, expires_at=datetime.now(UTC) - timedelta(seconds=1)
    )
    cases = [
        (None, None),
        ("sk_live_short", None),
        (f"{material.key_prefix}_{'0' * 32}", make_record(material)),
        (material.plaintext, make_record(material, status="revoked")),
        (material.plaintext, expired),
    ]
    for token, record in cases:
        with pytest.raises(HTTPException):
            await authenticate(token, record)


@pytest.mark.asyncio
async def test_require_scope():
    principal = AuthPrincipal(uuid4(), uuid4(), uuid4(), ("memories:read",))
    assert await require_scope("memories:read")(principal) is principal
    with pytest.raises(HTTPException) as exc:
        await require_scope("memories:write")(principal)
    assert exc.value.status_code == 403
    admin = AuthPrincipal(uuid4(), uuid4(), uuid4(), ("admin",))
    assert await require_scope("memories:write")(admin) is admin
