"""API key cache."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel
from redis.asyncio import Redis
from redis.exceptions import RedisError

from ..db.models import ApiKey

TTL_SECONDS = 300


class CachedApiKey(BaseModel):
    id: UUID
    tenant_id: UUID
    project_id: UUID
    key_prefix: str
    key_hash: str
    scopes: list[str]
    status: str
    expires_at: datetime | None
    revoked_at: datetime | None

    @classmethod
    def from_record(cls, record: ApiKey) -> "CachedApiKey":
        return cls(
            id=record.id, tenant_id=record.tenant_id, project_id=record.project_id,
            key_prefix=record.key_prefix, key_hash=record.key_hash,
            scopes=list(record.scopes or []), status=record.status,
            expires_at=record.expires_at, revoked_at=record.revoked_at,
        )


class ApiKeyCache:
    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    @staticmethod
    def key(prefix: str) -> str:
        return f"ak:{prefix}"

    async def get(self, prefix: str) -> CachedApiKey | None:
        try:
            raw = await self.redis.get(self.key(prefix))
        except RedisError:
            return None
        return CachedApiKey.model_validate_json(raw) if raw else None

    async def set(self, record: ApiKey) -> None:
        try:
            await self.redis.set(
                self.key(record.key_prefix),
                CachedApiKey.from_record(record).model_dump_json(),
                ex=TTL_SECONDS,
            )
        except RedisError:
            pass

    async def delete(self, prefix: str) -> None:
        try:
            await self.redis.delete(self.key(prefix))
        except RedisError:
            pass
