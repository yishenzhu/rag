"""Buffered API key last_used_at updates."""

import asyncio
import logging
from datetime import UTC, datetime
from uuid import UUID

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.engine import get_session_factory
from ..db.models import ApiKey

HASH_KEY = "last_used"
logger = logging.getLogger(__name__)


class LastUsedFlusher:
    def __init__(self, redis: Redis, session: AsyncSession) -> None:
        self.redis = redis
        self.session = session

    async def flush(self) -> int:
        try:
            data = await self.redis.hgetall(HASH_KEY)
        except RedisError:
            return 0
        if not data:
            return 0

        ids = [UUID(key) for key in data]
        await self.session.execute(
            update(ApiKey)
            .where(ApiKey.id.in_(ids))
            .values(last_used_at=datetime.now(UTC))
        )
        await self.session.commit()
        await self.redis.hdel(HASH_KEY, *data.keys())
        return len(ids)


async def flush_forever(redis: Redis, interval: float = 60.0) -> None:
    while True:
        await asyncio.sleep(interval)
        async with get_session_factory()() as session:
            try:
                await LastUsedFlusher(redis, session).flush()
            except Exception:
                logger.exception("last_used flush failed")
