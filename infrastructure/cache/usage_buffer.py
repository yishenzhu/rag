"""Buffered usage events."""

import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

from redis.asyncio import Redis
from redis.exceptions import RedisError

QUEUE_KEY = "usage:events"


class UsageBuffer:
    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    async def add(
        self,
        tenant_id: UUID,
        project_id: UUID,
        api_key_id: UUID | None,
        metric: str,
        quantity: int = 1,
        occurred_at: datetime | None = None,
    ) -> None:
        occurred_at = occurred_at or datetime.now(UTC)
        event = {
            "event_id": str(uuid4()),
            "tenant_id": str(tenant_id),
            "project_id": str(project_id),
            "api_key_id": str(api_key_id) if api_key_id else None,
            "metric": metric,
            "quantity": quantity,
            "period": occurred_at.strftime("%Y-%m"),
            "occurred_at": occurred_at.isoformat(),
        }
        try:
            await self.redis.rpush(QUEUE_KEY, json.dumps(event))
        except RedisError:
            pass
