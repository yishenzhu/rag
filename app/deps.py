"""Authentication dependencies for v1 routes."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from ..conf import get_settings
from ..infrastructure.cache.api_keys import ApiKeyCache
from ..infrastructure.cache.quota import QuotaLimiter
from ..infrastructure.cache.rate_limit import RateLimiter
from ..infrastructure.db.engine import get_session
from ..infrastructure.db.repositories import ApiKeyRepository, UserRepository
from ..infrastructure.vector.memory_index import MemoryIndex
from ..security.api_keys import ApiKeyError, has_scope, parse_api_key, verify_api_key
from ..security.auth import TokenError, decode_access_token
from .middleware import get_context

AUTH_HEADERS = {"WWW-Authenticate": "Bearer"}


@dataclass(frozen=True, slots=True)
class AuthPrincipal:
    api_key_id: UUID
    tenant_id: UUID
    project_id: UUID
    scopes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class UserPrincipal:
    user_id: UUID
    email: str
    tenant_id: UUID
    role: str


async def get_api_key_repository(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ApiKeyRepository:
    return ApiKeyRepository(session)


def get_redis(request: Request) -> Redis | None:
    return getattr(request.app.state, "redis", None)


def get_memory_index(request: Request) -> MemoryIndex:
    index = getattr(request.app.state, "memory_index", None)
    if index is None:
        raise HTTPException(503, "memory index unavailable")
    return index


async def require_api_key(
    request: Request,
    repo: Annotated[ApiKeyRepository, Depends(get_api_key_repository)],
    redis: Annotated[Redis | None, Depends(get_redis)],
) -> AuthPrincipal:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(401, "missing bearer token", headers=AUTH_HEADERS)

    try:
        parsed = parse_api_key(token)
    except ApiKeyError:
        raise HTTPException(401, "malformed api key", headers=AUTH_HEADERS) from None

    cache = ApiKeyCache(redis) if redis is not None else None
    record = await cache.get(parsed.key_prefix) if cache is not None else None
    if record is None:
        record = await repo.get_by_prefix(parsed.key_prefix)
        if record is not None and cache is not None:
            await cache.set(record)
    settings = get_settings()
    if record is None or not verify_api_key(
        token, record.key_hash, settings.api_key_pepper
    ):
        raise HTTPException(401, "invalid api key", headers=AUTH_HEADERS)

    now = datetime.now(UTC)
    if (
        record.status != "active"
        or record.revoked_at is not None
        or (record.expires_at is not None and record.expires_at <= now)
    ):
        raise HTTPException(401, "api key inactive or expired", headers=AUTH_HEADERS)

    if redis is not None:
        limiter = RateLimiter(
            redis, settings.rate_limit_rate, settings.rate_limit_burst
        )
        allowed, _ = await limiter.allow(f"key:{record.id}")
        if not allowed:
            raise HTTPException(
                429,
                "rate limit exceeded",
                headers={**AUTH_HEADERS, "Retry-After": "1"},
            )
        quota = QuotaLimiter(redis, settings.monthly_request_quota)
        allowed, _ = await quota.consume(record.tenant_id)
        if not allowed:
            raise HTTPException(
                429,
                "monthly quota exceeded",
                headers={**AUTH_HEADERS, "Retry-After": "3600"},
            )

    scopes = tuple(record.scopes or ())
    ctx = get_context()
    ctx.tenant_id = str(record.tenant_id)
    ctx.project_id = str(record.project_id)
    ctx.actor_type = "api_key"
    ctx.actor_id = str(record.id)
    ctx.scopes = scopes
    return AuthPrincipal(record.id, record.tenant_id, record.project_id, scopes)


async def require_user(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> UserPrincipal:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(401, "missing bearer token", headers=AUTH_HEADERS)

    try:
        payload = decode_access_token(token, get_settings().jwt_secret)
    except TokenError:
        raise HTTPException(401, "invalid token", headers=AUTH_HEADERS) from None

    user = await UserRepository(session).get_by_id(payload.user_id)
    if user is None or user.status != "active":
        raise HTTPException(401, "invalid token", headers=AUTH_HEADERS)

    ctx = get_context()
    ctx.tenant_id = str(payload.tenant_id)
    ctx.actor_type = "user"
    ctx.actor_id = str(user.id)
    return UserPrincipal(user.id, user.email, payload.tenant_id, payload.role)


def require_scope(required: str):
    async def dependency(
        principal: Annotated[AuthPrincipal, Depends(require_api_key)],
    ) -> AuthPrincipal:
        if not has_scope(principal.scopes, required):
            raise HTTPException(403, f"missing scope: {required}")
        return principal

    return dependency


def require_role(*allowed: str):
    async def dependency(
        principal: Annotated[UserPrincipal, Depends(require_user)],
    ) -> UserPrincipal:
        if principal.role not in allowed:
            raise HTTPException(403, f"requires role: {', '.join(allowed)}")
        return principal

    return dependency
