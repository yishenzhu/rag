"""Monthly request quota counters."""

from datetime import UTC, datetime
from uuid import UUID

from redis.asyncio import Redis
from redis.exceptions import RedisError

QUOTA_SCRIPT = """
local current = tonumber(redis.call('GET', KEYS[1])) or 0
local limit = tonumber(ARGV[1])
local amount = tonumber(ARGV[2])
if current + amount > limit then
  return {0, current}
end
local new = redis.call('INCRBY', KEYS[1], amount)
if current == 0 then
  redis.call('EXPIRE', KEYS[1], tonumber(ARGV[3]))
end
return {1, new}
"""

TTL_SECONDS = 40 * 24 * 3600


class QuotaLimiter:
    def __init__(self, redis: Redis, limit: int) -> None:
        self.redis = redis
        self.limit = max(1, limit)

    @staticmethod
    def key(tenant_id: UUID, period: str) -> str:
        return f"quota:{tenant_id}:{period}:requests"

    async def consume(
        self, tenant_id: UUID, amount: int = 1
    ) -> tuple[bool, int]:
        period = datetime.now(UTC).strftime("%Y-%m")
        try:
            result = await self.redis.eval(
                QUOTA_SCRIPT,
                1,
                self.key(tenant_id, period),
                self.limit,
                amount,
                TTL_SECONDS,
            )
        except RedisError:
            return True, 0
        return bool(result[0]), int(result[1])
