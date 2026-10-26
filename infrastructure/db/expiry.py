"""Expire memories whose TTL has passed."""

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .engine import get_session_factory
from .models import Memory
from .outbox import enqueue_memory_delete

BATCH_SIZE = 500
INTERVAL_SECONDS = 60.0
logger = logging.getLogger(__name__)


async def expire_memories(
    session: AsyncSession, now: datetime | None = None, limit: int = BATCH_SIZE
) -> int:
    now = now or datetime.now(UTC)
    statement = (
        select(Memory)
        .where(
            Memory.expires_at.is_not(None),
            Memory.expires_at <= now,
            Memory.deleted_at.is_(None),
        )
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    memories = (await session.execute(statement)).scalars().all()
    for memory in memories:
        memory.status = "expired"
        memory.deleted_at = now
        memory.updated_at = now
        enqueue_memory_delete(session, memory)
    if memories:
        await session.commit()
    return len(memories)


async def expire_forever(interval: float = INTERVAL_SECONDS) -> None:
    while True:
        async with get_session_factory()() as session:
            try:
                await expire_memories(session)
            except Exception:
                await session.rollback()
                logger.exception("memory expiry failed")
        await asyncio.sleep(interval)
