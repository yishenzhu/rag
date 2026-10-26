"""Outbox relay: publish pending events to Kafka."""

import asyncio
import json
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import OutboxEvent
from ..db.repositories import OutboxRepository
from .kafka import KafkaProducer


def build_message(event: OutboxEvent) -> bytes:
    return json.dumps(
        {
            "event_id": str(event.event_id),
            "event_type": event.event_type,
            "occurred_at": event.created_at.isoformat(),
            "tenant_id": event.payload.get("tenant_id"),
            "project_id": event.payload.get("project_id"),
            "payload": event.payload,
        }
    ).encode()


class OutboxRelay:
    def __init__(
        self,
        session: AsyncSession,
        producer: KafkaProducer,
        batch_size: int = 100,
        max_attempts: int = 5,
    ) -> None:
        self.session = session
        self.producer = producer
        self.batch_size = batch_size
        self.max_attempts = max_attempts

    async def run_once(self) -> int:
        events = await OutboxRepository(self.session).claim_pending(
            self.batch_size
        )
        for event in events:
            try:
                await self.producer.send(
                    event.topic, event.partition_key, build_message(event)
                )
                event.status = "published"
                event.published_at = datetime.now(UTC)
                event.last_error = None
            except Exception as exc:  # noqa: BLE001
                event.attempts += 1
                event.last_error = str(exc)[:1000]
                if event.attempts >= self.max_attempts:
                    event.status = "failed"
                else:
                    event.available_at = datetime.now(UTC) + timedelta(
                        seconds=min(60, 2**event.attempts)
                    )
        await self.session.commit()
        return len(events)

    async def run_forever(self, interval: float = 1.0) -> None:
        while True:
            if await self.run_once() == 0:
                await asyncio.sleep(interval)
