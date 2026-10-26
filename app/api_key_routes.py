"""API key management routes."""

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from redis.asyncio import Redis
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..conf import get_settings
from ..infrastructure.cache.api_keys import ApiKeyCache
from ..infrastructure.db.engine import get_session
from ..infrastructure.db.models import ApiKey, Project
from ..infrastructure.db.repositories import ApiKeyRepository
from ..security.api_keys import ApiKeyError, generate_api_key, normalize_scopes
from .deps import UserPrincipal, get_redis, require_role

router = APIRouter(prefix="/api-keys", tags=["api-keys"])


class CreateApiKeyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    project_id: UUID
    scopes: list[str] = Field(min_length=1)
    expires_at: datetime | None = None


class ApiKeyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    key_prefix: str
    scopes: list[str]
    status: str
    created_at: datetime
    expires_at: datetime | None
    last_used_at: datetime | None


class CreatedApiKeyResponse(ApiKeyResponse):
    key: str


@router.post("", response_model=CreatedApiKeyResponse, status_code=201)
async def create_api_key(
    req: CreateApiKeyRequest,
    principal: Annotated[UserPrincipal, Depends(require_role("owner", "admin"))],
    session: Annotated[AsyncSession, Depends(get_session)],
    redis: Annotated[Redis | None, Depends(get_redis)],
) -> CreatedApiKeyResponse:
    project = await session.get(Project, req.project_id)
    if project is None or project.tenant_id != principal.tenant_id:
        raise HTTPException(404, "project not found")
    try:
        scopes = normalize_scopes(req.scopes)
    except ApiKeyError as exc:
        raise HTTPException(400, str(exc)) from None

    settings = get_settings()
    for _ in range(3):
        material = generate_api_key(settings.api_key_pepper)
        record = ApiKey(
            id=uuid4(),
            tenant_id=principal.tenant_id,
            project_id=project.id,
            name=req.name,
            key_prefix=material.key_prefix,
            key_hash=material.key_hash,
            scopes=list(scopes),
            status="active",
            expires_at=req.expires_at,
            created_at=datetime.now(UTC),
        )
        session.add(record)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            continue
        if redis is not None:
            await ApiKeyCache(redis).set(record)
        data = ApiKeyResponse.model_validate(record).model_dump()
        return CreatedApiKeyResponse(**data, key=material.plaintext)

    raise HTTPException(409, "could not allocate api key prefix")


@router.get("", response_model=list[ApiKeyResponse])
async def list_api_keys(
    principal: Annotated[UserPrincipal, Depends(require_role("owner", "admin"))],
    session: Annotated[AsyncSession, Depends(get_session)],
    project_id: UUID | None = None,
) -> list[ApiKeyResponse]:
    records = await ApiKeyRepository(session).list_for_tenant(
        principal.tenant_id, project_id
    )
    return [ApiKeyResponse.model_validate(record) for record in records]


@router.delete("/{key_id}", status_code=204)
async def revoke_api_key(
    key_id: UUID,
    principal: Annotated[UserPrincipal, Depends(require_role("owner", "admin"))],
    session: Annotated[AsyncSession, Depends(get_session)],
    redis: Annotated[Redis | None, Depends(get_redis)],
) -> None:
    record = await ApiKeyRepository(session).get_for_tenant(
        key_id, principal.tenant_id
    )
    if record is None:
        raise HTTPException(404, "api key not found")

    record.status = "revoked"
    record.revoked_at = datetime.now(UTC)
    await session.commit()
    if redis is not None:
        await ApiKeyCache(redis).delete(record.key_prefix)
