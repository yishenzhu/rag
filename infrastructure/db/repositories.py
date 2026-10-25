"""Database repositories."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import ApiKey, User


class ApiKeyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_prefix(self, key_prefix: str) -> ApiKey | None:
        result = await self.session.execute(select(ApiKey).where(ApiKey.key_prefix == key_prefix))
        return result.scalar_one_or_none()


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_email(self, email: str) -> User | None:
        result = await self.session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def get_by_id(self, user_id: UUID) -> User | None:
        return await self.session.get(User, user_id)
