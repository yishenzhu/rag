"""Project routes."""

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..infrastructure.db.engine import get_session
from ..infrastructure.db.models import Project
from ..infrastructure.db.repositories import ProjectRepository
from .deps import UserPrincipal, require_role, require_user
from .slugs import make_slug

router = APIRouter(prefix="/projects", tags=["projects"])


class CreateProjectRequest(BaseModel):
    name: str = Field(min_length=2, max_length=128)
    slug: str | None = Field(
        default=None,
        min_length=2,
        max_length=64,
        pattern=r"^[a-z0-9-]+$",
    )


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    slug: str
    settings: dict
    created_at: datetime


@router.get("", response_model=list[ProjectResponse])
async def list_projects(
    principal: Annotated[UserPrincipal, Depends(require_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[ProjectResponse]:
    records = await ProjectRepository(session).list_for_tenant(principal.tenant_id)
    return [ProjectResponse.model_validate(record) for record in records]


@router.post("", response_model=ProjectResponse, status_code=201)
async def create_project(
    req: CreateProjectRequest,
    principal: Annotated[UserPrincipal, Depends(require_role("owner", "admin"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ProjectResponse:
    project = Project(
        id=uuid4(),
        tenant_id=principal.tenant_id,
        name=req.name.strip(),
        slug=req.slug or make_slug(req.name, "project"),
        settings={},
        created_at=datetime.now(UTC),
    )
    session.add(project)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(409, "project slug already exists") from None
    return ProjectResponse.model_validate(project)
