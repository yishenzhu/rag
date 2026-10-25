"""Database repositories."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import ApiKey, Membership, Memory, Project, User


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

    async def get_by_content_hash(
        self, project_id: UUID, content_hash: str
    ) -> Memory | None:
        result = await self.session.execute(
            select(Memory).where(
                Memory.project_id == project_id,
                Memory.content_hash == content_hash,
                Memory.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()
