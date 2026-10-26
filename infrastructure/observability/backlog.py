"""Periodic backlog gauges scraped from PostgreSQL."""

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.engine import get_session_factory
from ..db.models import Memory, OutboxEvent
from .metrics import (
    MEMORIES_BY_STATUS,
    OUTBOX_OLDEST_PENDING_SECONDS,
    OUTBOX_PENDING,
)

logger = logging.getLogger(__name__)

BACKLOG_INTERVAL_SECONDS = 15.0
STATUSES = ("pending", "active", "failed", "deleted", "expired")


async def collect_backlog(session: AsyncSession) -> None:
    pending = await session.scalar(
        select(func.count())
        .select_from(OutboxEvent)
        .where(OutboxEvent.status == "pending")
    ) or 0
    OUTBOX_PENDING.set(pending)

    oldest = await session.scalar(
        select(func.min(OutboxEvent.created_at)).where(
            OutboxEvent.status == "pending"
        )
    )
    OUTBOX_OLDEST_PENDING_SECONDS.set(
        0.0 if oldest is None
        else max((datetime.now(UTC) - oldest).total_seconds(), 0.0)
    )

    rows = (
        await session.execute(
            select(Memory.status, func.count()).group_by(Memory.status)
        )
    ).all()
    counts = {row[0]: row[1] for row in rows}
    for status in STATUSES:
        MEMORIES_BY_STATUS.labels(status).set(counts.get(status, 0))


async def refresh_backlog_forever(
    interval: float = BACKLOG_INTERVAL_SECONDS,
) -> None:
    while True:
        async with get_session_factory()() as session:
            try:
                await collect_backlog(session)
            except Exception:
                logger.exception("backlog metrics refresh failed")
        await asyncio.sleep(interval)
