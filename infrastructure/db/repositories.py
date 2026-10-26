"""Database repositories."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    ApiKey,
    Membership,
    Memory,
    OutboxEvent,
    Project,
    UsageLedger,
    User,
)


class ApiKeyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_prefix(self, key_prefix: str) -> ApiKey | None:
        result = await self.session.execute(select(ApiKey).where(ApiKey.key_prefix == key_prefix))
        return result.scalar_one_or_none()

    async def list_for_tenant(
        self, tenant_id: UUID, project_id: UUID | None = None
    ) -> list[ApiKey]:
        stmt = select(ApiKey).where(ApiKey.tenant_id == tenant_id)
        if project_id is not None:
            stmt = stmt.where(ApiKey.project_id == project_id)
        result = await self.session.execute(stmt.order_by(ApiKey.created_at.desc()))
        return list(result.scalars().all())

    async def get_for_tenant(self, key_id: UUID, tenant_id: UUID) -> ApiKey | None:
        result = await self.session.execute(
            select(ApiKey).where(ApiKey.id == key_id, ApiKey.tenant_id == tenant_id)
        )
        return result.scalar_one_or_none()


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_email(self, email: str) -> User | None:
        result = await self.session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def get_by_id(self, user_id: UUID) -> User | None:
        return await self.session.get(User, user_id)


class MembershipRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_for_user(self, user_id: UUID) -> list[Membership]:
        result = await self.session.execute(
            select(Membership).where(Membership.user_id == user_id)
        )
        return list(result.scalars().all())


class ProjectRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_for_tenant(self, tenant_id: UUID) -> list[Project]:
        result = await self.session.execute(
            select(Project)
            .where(Project.tenant_id == tenant_id)
            .order_by(Project.created_at.desc())
        )
        return list(result.scalars().all())


class MemoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, memory_id: UUID) -> Memory | None:
        return await self.session.get(Memory, memory_id)

    async def get_by_content_hash(
        self,
        project_id: UUID,
        content_hash: str,
        exclude_id: UUID | None = None,
    ) -> Memory | None:
        conditions = [
            Memory.project_id == project_id,
            Memory.content_hash == content_hash,
            Memory.deleted_at.is_(None),
        ]
        if exclude_id is not None:
            conditions.append(Memory.id != exclude_id)
        result = await self.session.execute(select(Memory).where(*conditions))
        return result.scalar_one_or_none()

    async def get_for_scope(
        self, memory_id: UUID, tenant_id: UUID, project_id: UUID
    ) -> Memory | None:
        result = await self.session.execute(
            select(Memory).where(
                Memory.id == memory_id,
                Memory.tenant_id == tenant_id,
                Memory.project_id == project_id,
                Memory.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def list_for_scope(
        self, tenant_id: UUID, project_id: UUID, limit: int, offset: int
    ) -> list[Memory]:
        result = await self.session.execute(
            select(Memory)
            .where(
                Memory.tenant_id == tenant_id,
                Memory.project_id == project_id,
                Memory.deleted_at.is_(None),
            )
            .order_by(Memory.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())


class OutboxRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def claim_pending(self, limit: int) -> list[OutboxEvent]:
        result = await self.session.execute(
            select(OutboxEvent)
            .where(
                OutboxEvent.status == "pending",
                OutboxEvent.available_at <= func.now(),
            )
            .order_by(OutboxEvent.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list(result.scalars().all())


class UsageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def totals(
        self, tenant_id: UUID, period: str
    ) -> dict[str, int]:
        result = await self.session.execute(
            select(UsageLedger.metric, func.sum(UsageLedger.quantity))
            .where(
                UsageLedger.tenant_id == tenant_id,
                UsageLedger.period == period,
            )
            .group_by(UsageLedger.metric)
        )
        return {
            metric: int(quantity or 0)
            for metric, quantity in result.all()
        }

    async def grouped(
        self, tenant_id: UUID, period: str, group_by: str
    ):
        if group_by == "api_key":
            dimension = UsageLedger.api_key_id
        elif group_by == "model":
            dimension = UsageLedger.model
        else:
            dimension = func.date(UsageLedger.occurred_at)
        result = await self.session.execute(
            select(
                dimension,
                UsageLedger.metric,
                func.sum(UsageLedger.quantity),
            )
            .where(
                UsageLedger.tenant_id == tenant_id,
                UsageLedger.period == period,
            )
            .group_by(dimension, UsageLedger.metric)
            .order_by(dimension)
        )
        return result.all()
