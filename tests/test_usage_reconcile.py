"""Usage reconciliation tests."""

from uuid import uuid4

import pytest
from fastapi import HTTPException
from rag.app.deps import UserPrincipal
from rag.app.usage_routes import reconcile_usage
from rag.infrastructure.cache.usage_reconcile import UsageReconciler
from redis.exceptions import RedisError


class FakeSession:
    def __init__(self, value):
        self.value = value

    async def scalar(self, stmt):
        return self.value


class FakeRedis:
    def __init__(self, value=None, fail=False):
        self.value = value
        self.fail = fail

    async def get(self, key):
        if self.fail:
            raise RedisError("down")
        return self.value


@pytest.mark.asyncio
async def test_reconcile_counts():
    tenant = uuid4()
    data = await UsageReconciler(
        FakeRedis("12"), FakeSession(10)
    ).check(tenant, "2026-10")

    assert (data["redis"], data["ledger"], data["difference"]) == (
        12,
        10,
        2,
    )


@pytest.mark.asyncio
async def test_reconcile_fail_open_and_route():
    principal = UserPrincipal(uuid4(), "a@b.com", uuid4(), "owner")
    result = await reconcile_usage(
        principal, FakeSession(5), FakeRedis(fail=True), "2026-10"
    )
    assert result.redis is None
    assert result.ledger == 5
    assert result.difference is None

    with pytest.raises(HTTPException) as exc:
        await reconcile_usage(principal, FakeSession(0), None, "2026-10")
    assert exc.value.status_code == 503
