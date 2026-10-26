"""HTTP idempotency keys."""

import json
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import RedisError

PENDING = "pending"
PENDING_TTL = 60
DONE_TTL = 86400


def encode_record(request_hash: str, status: int, body: Any) -> str:
    return json.dumps({"hash": request_hash, "status": status, "body": body})


def decode_record(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        record = json.loads(raw)
    except ValueError:
        return None
    return record if isinstance(record, dict) and "hash" in record else None


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
        record = decode_record(existing)
        stored_hash = record["hash"] if record else existing
        if stored_hash == request_hash:
            return "duplicate"
        return "reused"

    async def complete(
        self,
        scope: str,
        key: str,
        request_hash: str,
        status: int = 204,
        body: Any = None,
    ) -> None:
        try:
            await self.redis.set(
                self.key(scope, key),
                encode_record(request_hash, status, body),
                ex=DONE_TTL,
            )
        except RedisError:
            pass

    async def response(
        self, scope: str, key: str, request_hash: str
    ) -> tuple[int, Any] | None:
        try:
            record = decode_record(await self.redis.get(self.key(scope, key)))
        except RedisError:
            return None
        if record is None or record["hash"] != request_hash:
            return None
        if record.get("body") is None:
            return None
        return int(record.get("status", 204)), record["body"]

    async def release(self, scope: str, key: str) -> None:
        try:
            await self.redis.delete(self.key(scope, key))
        except RedisError:
            pass
