"""Memory routes."""

import hashlib
import logging
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..infrastructure.db.engine import get_session
from ..infrastructure.db.models import Memory
from ..infrastructure.db.repositories import MemoryRepository
from ..infrastructure.vector.memory_index import MemoryIndex
from .deps import AuthPrincipal, get_memory_index, require_scope

router = APIRouter(prefix="/memories", tags=["memories"])
logger = logging.getLogger(__name__)


class CreateMemoryRequest(BaseModel):
    content: str = Field(min_length=1, max_length=20000)
    metadata: dict = Field(default_factory=dict)
    external_id: str | None = Field(default=None, max_length=255)
    expires_at: datetime | None = None


class UpdateMemoryRequest(BaseModel):
    content: str | None = Field(default=None, min_length=1, max_length=20000)
    metadata: dict | None = None
    external_id: str | None = Field(default=None, max_length=255)
    expires_at: datetime | None = None
    importance: float | None = Field(default=None, ge=0, le=1)


class MemoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    project_id: UUID
    external_id: str | None
    content: str
    metadata: dict = Field(validation_alias="memory_metadata")
    status: str
    source: str | None
    importance: float
    expires_at: datetime | None
    created_at: datetime
    updated_at: datetime


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


@router.post("", response_model=MemoryResponse, status_code=201)
async def create_memory(
    req: CreateMemoryRequest,
    principal: Annotated[AuthPrincipal, Depends(require_scope("memories:write"))],
    session: Annotated[AsyncSession, Depends(get_session)],
    index: Annotated[MemoryIndex, Depends(get_memory_index)],
) -> MemoryResponse:
    repo = MemoryRepository(session)
    digest = content_hash(req.content)
    existing = await repo.get_by_content_hash(principal.project_id, digest)
    if existing is not None:
        return MemoryResponse.model_validate(existing)

    now = datetime.now(UTC)
    memory = Memory(
        id=uuid4(),
        tenant_id=principal.tenant_id,
        project_id=principal.project_id,
        external_id=req.external_id,
        content=req.content,
        content_hash=digest,
        memory_metadata=req.metadata,
        status="active",
        source="api",
        importance=0.5,
        expires_at=req.expires_at,
        created_at=now,
        updated_at=now,
    )
    session.add(memory)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        existing = await repo.get_by_content_hash(principal.project_id, digest)
        if existing is not None:
            return MemoryResponse.model_validate(existing)
        raise HTTPException(409, "memory conflict") from None
    try:
        await index.index(memory)
        memory.qdrant_point_id = memory.id
        await session.commit()
    except Exception:
        logger.exception("memory indexing failed: %s", memory.id)
    return MemoryResponse.model_validate(memory)


@router.get("", response_model=list[MemoryResponse])
async def list_memories(
    principal: Annotated[AuthPrincipal, Depends(require_scope("memories:read"))],
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> list[MemoryResponse]:
    records = await MemoryRepository(session).list_for_scope(
        principal.tenant_id, principal.project_id, limit, offset
    )
    return [MemoryResponse.model_validate(record) for record in records]


@router.get("/{memory_id}", response_model=MemoryResponse)
async def get_memory(
    memory_id: UUID,
    principal: Annotated[AuthPrincipal, Depends(require_scope("memories:read"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MemoryResponse:
    record = await MemoryRepository(session).get_for_scope(
        memory_id, principal.tenant_id, principal.project_id
    )
    if record is None:
        raise HTTPException(404, "memory not found")
    return MemoryResponse.model_validate(record)


@router.patch("/{memory_id}", response_model=MemoryResponse)
async def update_memory(
    memory_id: UUID,
    req: UpdateMemoryRequest,
    principal: Annotated[AuthPrincipal, Depends(require_scope("memories:write"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MemoryResponse:
    repo = MemoryRepository(session)
    record = await repo.get_for_scope(
        memory_id, principal.tenant_id, principal.project_id
    )
    if record is None:
        raise HTTPException(404, "memory not found")

    changes = req.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(400, "no fields to update")
    if "content" in changes:
        if changes["content"] is None:
            raise HTTPException(400, "content cannot be null")
        digest = content_hash(changes["content"])
        existing = await repo.get_by_content_hash(
            principal.project_id, digest, exclude_id=memory_id
        )
        if existing is not None:
            raise HTTPException(409, "duplicate memory")
        record.content = changes["content"]
        record.content_hash = digest
    if "metadata" in changes:
        record.memory_metadata = changes["metadata"] or {}
    if "external_id" in changes:
        record.external_id = changes["external_id"]
    if "expires_at" in changes:
        record.expires_at = changes["expires_at"]
    if "importance" in changes and changes["importance"] is not None:
        record.importance = changes["importance"]
    record.updated_at = datetime.now(UTC)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(409, "duplicate memory") from None
    return MemoryResponse.model_validate(record)


@router.delete("/{memory_id}", status_code=204)
async def delete_memory(
    memory_id: UUID,
    principal: Annotated[AuthPrincipal, Depends(require_scope("memories:write"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    record = await MemoryRepository(session).get_for_scope(
        memory_id, principal.tenant_id, principal.project_id
    )
    if record is None:
        raise HTTPException(404, "memory not found")

    now = datetime.now(UTC)
    record.status = "deleted"
    record.deleted_at = now
    record.updated_at = now
    await session.commit()
