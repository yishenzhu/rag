"""Reconcile Redis quota counters with the usage ledger."""

from uuid import UUID

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import UsageLedger
from .quota import QuotaLimiter


class UsageReconciler:
    def __init__(self, redis: Redis, session: AsyncSession) -> None:
        self.redis = redis
        self.session = session

    async def check(self, tenant_id: UUID, period: str) -> dict:
        ledger = await self.session.scalar(
            select(func.coalesce(func.sum(UsageLedger.quantity), 0))
            .where(
                UsageLedger.tenant_id == tenant_id,
                UsageLedger.period == period,
                UsageLedger.metric == "request",
            )
        )
        ledger_count = int(ledger or 0)
        try:
            raw = await self.redis.get(
                QuotaLimiter.key(tenant_id, period)
            )
            redis_count = int(raw or 0)
        except RedisError:
            redis_count = None
        return {
            "tenant_id": tenant_id,
            "period": period,
            "redis": redis_count,
            "ledger": ledger_count,
            "difference": (
                redis_count - ledger_count
                if redis_count is not None
                else None
            ),
        }
