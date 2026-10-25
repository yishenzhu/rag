"""Outbox event helpers."""

from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from .models import Memory, OutboxEvent

TOPIC_MEMORY_INGEST = "memory.ingest.v1"
TOPIC_MEMORY_DELETE = "memory.delete.v1"


def build_memory_event(
    memory: Memory, topic: str, event_type: str
) -> OutboxEvent:
    return OutboxEvent(
        event_id=uuid4(),
        topic=topic,
        partition_key=f"{memory.project_id}:{memory.id}",
        event_type=event_type,
        payload={
            "memory_id": str(memory.id),
            "tenant_id": str(memory.tenant_id),
            "project_id": str(memory.project_id),
            "content_hash": memory.content_hash,
        },
        status="pending",
        attempts=0,
    )


def enqueue_memory_ingest(
    session: AsyncSession, memory: Memory, event_type: str
) -> OutboxEvent:
    event = build_memory_event(memory, TOPIC_MEMORY_INGEST, event_type)
    session.add(event)
    return event


def enqueue_memory_delete(
    session: AsyncSession, memory: Memory
) -> OutboxEvent:
    event = build_memory_event(memory, TOPIC_MEMORY_DELETE, "memory.deleted")
    session.add(event)
    return event
