"""Flush buffered usage events into PostgreSQL."""

import asyncio
import json
import logging
from datetime import datetime
from uuid import UUID

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.engine import get_session_factory
from ..db.models import UsageLedger
from ..observability.metrics import USAGE_FLUSH_FAILURES
from .usage_buffer import QUEUE_KEY

BATCH_SIZE = 100
logger = logging.getLogger(__name__)


class UsageFlusher:
    def __init__(self, redis: Redis, session: AsyncSession, batch_size: int = BATCH_SIZE) -> None:
        self.redis = redis
        self.session = session
        self.batch_size = batch_size

    async def flush(self) -> int:
        try:
            raw = await self.redis.lpop(QUEUE_KEY, self.batch_size)
        except RedisError:
            return 0
        if not raw:
            return 0

        rows = []
        for item in raw:
            event = json.loads(item)
            rows.append({
                "event_id": UUID(event["event_id"]),
                "tenant_id": UUID(event["tenant_id"]),
                "project_id": UUID(event["project_id"]),
                "api_key_id": UUID(event["api_key_id"]) if event.get("api_key_id") else None,
                "metric": event["metric"],
                "quantity": int(event["quantity"]),
                "period": event["period"],
                "occurred_at": datetime.fromisoformat(event["occurred_at"]),
            })

        try:
            await self.session.execute(
                insert(UsageLedger).values(rows).on_conflict_do_nothing(index_elements=["event_id"])
            )
            await self.session.commit()
        except Exception:
            try:
                await self.redis.lpush(QUEUE_KEY, *reversed(raw))
            except RedisError:
                logger.warning("usage batch requeue failed", exc_info=True)
            raise
        return len(rows)


async def flush_forever(redis: Redis, interval: float = 60.0) -> None:
    while True:
        await asyncio.sleep(interval)
        async with get_session_factory()() as session:
            try:
                await UsageFlusher(redis, session).flush()
            except Exception:
                USAGE_FLUSH_FAILURES.inc()
                logger.exception("usage flush failed")
