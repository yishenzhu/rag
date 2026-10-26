"""HTTP idempotency keys."""

from redis.asyncio import Redis
from redis.exceptions import RedisError

PENDING = "pending"
PENDING_TTL = 60
DONE_TTL = 86400


class IdempotencyStore:
    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    @staticmethod
    def key(scope: str, key: str) -> str:
        return f"idem:{scope}:{key}"

    async def claim(self, scope: str, key: str, request_hash: str) -> str:
        cache_key = self.key(scope, key)
        try:
            if await self.redis.set(
                cache_key, PENDING, nx=True, ex=PENDING_TTL
            ):
                return "claimed"
            existing = await self.redis.get(cache_key)
        except RedisError:
            return "claimed"
        if existing == PENDING:
            return "in_progress"
        if existing == request_hash:
            return "duplicate"
        return "reused"

    async def complete(self, scope: str, key: str, request_hash: str) -> None:
        try:
            await self.redis.set(
                self.key(scope, key), request_hash, ex=DONE_TTL
            )
        except RedisError:
            pass

    async def release(self, scope: str, key: str) -> None:
        try:
            await self.redis.delete(self.key(scope, key))
        except RedisError:
            pass
