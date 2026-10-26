"""Usage routes."""

from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from ..infrastructure.db.engine import get_session
from ..infrastructure.db.repositories import UsageRepository
from .deps import UserPrincipal, require_user

router = APIRouter(prefix="/usage", tags=["usage"])


class UsageGroup(BaseModel):
    dimension: str
    metric: str
    quantity: int


class UsageSummary(BaseModel):
    tenant_id: UUID
    period: str
    totals: dict[str, int]
    groups: list[UsageGroup]


class UsageEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    event_id: UUID
    tenant_id: UUID
    project_id: UUID
    api_key_id: UUID | None
    metric: str
    quantity: int
    model: str | None
    period: str
    occurred_at: datetime


@router.get("", response_model=UsageSummary)
async def get_usage(
    principal: Annotated[UserPrincipal, Depends(require_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    period: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}$")] = None,
    group_by: Annotated[
        Literal["day", "api_key", "model"], Query()
    ] = "day",
) -> UsageSummary:
    period = period or datetime.now(UTC).strftime("%Y-%m")
    repo = UsageRepository(session)
    totals = await repo.totals(principal.tenant_id, period)
    rows = await repo.grouped(principal.tenant_id, period, group_by)
    groups = [
        UsageGroup(
            dimension=str(row[0]) if row[0] is not None else "unknown",
            metric=row[1],
            quantity=int(row[2] or 0),
        )
        for row in rows
    ]
    return UsageSummary(
        tenant_id=principal.tenant_id,
        period=period,
        totals=totals,
        groups=groups,
    )


@router.get("/events", response_model=list[UsageEventResponse])
async def list_usage_events(
    principal: Annotated[UserPrincipal, Depends(require_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    period: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}$")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[UsageEventResponse]:
    period = period or datetime.now(UTC).strftime("%Y-%m")
    records = await UsageRepository(session).events(
        principal.tenant_id, period, limit, offset
    )
    return [
        UsageEventResponse.model_validate(record) for record in records
    ]
