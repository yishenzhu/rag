"""Usage route tests."""

from datetime import date
from uuid import uuid4

import pytest
from rag.app.deps import UserPrincipal
from rag.app.usage_routes import get_usage


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class FakeSession:
    def __init__(self, results):
        self.results = list(results)

    async def execute(self, stmt):
        return FakeResult(self.results.pop(0))


@pytest.mark.asyncio
async def test_usage_summary():
    tenant = uuid4()
    principal = UserPrincipal(uuid4(), "a@b.com", tenant, "owner")
    session = FakeSession([
        [("request", 10), ("tokens_in", 5)],
        [(date(2026, 10, 1), "request", 6), (date(2026, 10, 2), "request", 4)],
    ])
    summary = await get_usage(principal, session, "2026-10", "day")

    assert summary.tenant_id == tenant
    assert summary.period == "2026-10"
    assert summary.totals == {"request": 10, "tokens_in": 5}
    assert (summary.groups[0].dimension, summary.groups[0].quantity) == (
        "2026-10-01", 6
    )


@pytest.mark.asyncio
async def test_usage_unknown_model_and_default_period():
    principal = UserPrincipal(uuid4(), "a@b.com", uuid4(), "member")
    session = FakeSession([
        [("request", 1)],
        [(None, "request", 1)],
    ])
    summary = await get_usage(principal, session, None, "model")

    assert summary.period
    assert summary.groups[0].dimension == "unknown"
