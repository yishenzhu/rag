"""Backlog gauge tests."""

from datetime import UTC, datetime, timedelta

import pytest
from prometheus_client import REGISTRY
from rag.infrastructure.observability.backlog import collect_backlog


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class FakeSession:
    def __init__(self, scalars, rows):
        self.scalars = list(scalars)
        self.rows = rows

    async def scalar(self, stmt):
        return self.scalars.pop(0)

    async def execute(self, stmt):
        return FakeResult(self.rows)


def _gauge(name, labels=None):
    return REGISTRY.get_sample_value(name, labels or {})


@pytest.mark.asyncio
async def test_backlog_empty():
    await collect_backlog(FakeSession([0, None], []))
    assert _gauge("outbox_pending") == 0
    assert _gauge("outbox_oldest_pending_seconds") == 0
    assert _gauge("memories_by_status", {"status": "active"}) == 0


@pytest.mark.asyncio
async def test_backlog_reports_counts():
    oldest = datetime.now(UTC) - timedelta(seconds=42)
    await collect_backlog(
        FakeSession([7, oldest], [("pending", 3), ("active", 11)])
    )
    assert _gauge("outbox_pending") == 7
    assert 40 <= _gauge("outbox_oldest_pending_seconds") <= 45
    assert _gauge("memories_by_status", {"status": "pending"}) == 3
    assert _gauge("memories_by_status", {"status": "active"}) == 11
    assert _gauge("memories_by_status", {"status": "failed"}) == 0
