"""Outbox relay tests (fake producer and session)."""

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from rag.infrastructure.queue.relay import OutboxRelay


class FakeResult:
    def __init__(self, many):
        self.many = many

    def scalars(self): return self
    def all(self): return self.many


class FakeSession:
    def __init__(self, events):
        self.events = events
        self.committed = False

    async def execute(self, stmt):
        return FakeResult(self.events)

    async def commit(self): self.committed = True


class FakeProducer:
    def __init__(self, fail=False):
        self.fail = fail
        self.sent = []

    async def send(self, topic, key, value):
        if self.fail:
            raise RuntimeError("kafka down")
        self.sent.append((topic, key, value))


def make_event(**overrides):
    values = {
        "event_id": uuid4(),
        "topic": "memory.ingest.v1",
        "partition_key": "project:memory",
        "event_type": "memory.created",
        "payload": {"memory_id": "m1", "tenant_id": "t1", "project_id": "p1"},
        "status": "pending",
        "attempts": 0,
        "available_at": datetime.now(UTC),
        "created_at": datetime.now(UTC),
        "published_at": None,
        "last_error": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.asyncio
async def test_relay_publishes_event():
    event = make_event()
    session = FakeSession([event])
    producer = FakeProducer()
    count = await OutboxRelay(session, producer).run_once()
    assert count == 1
    assert event.status == "published"
    assert event.published_at is not None
    assert session.committed
    topic, key, value = producer.sent[0]
    message = json.loads(value)
    assert topic == event.topic and key == event.partition_key
    assert message["event_id"] == str(event.event_id)
    assert message["payload"]["memory_id"] == "m1"


@pytest.mark.asyncio
async def test_relay_marks_failed_after_max_attempts():
    event = make_event()
    relay = OutboxRelay(
        FakeSession([event]), FakeProducer(fail=True), max_attempts=1
    )
    await relay.run_once()

    assert event.status == "failed"
    assert event.attempts == 1
    assert "kafka down" in event.last_error
