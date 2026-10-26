"""Memory event consumer logic."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from ..db.repositories import MemoryRepository
from ..vector.memory_index import MemoryIndex


class MemoryConsumer:
    def __init__(self, session: AsyncSession, index: MemoryIndex) -> None:
        self.session = session
        self.index = index

    async def handle(self, event: dict) -> None:
        payload = event.get("payload") or {}
        memory_id = UUID(payload["memory_id"])
        memory = await MemoryRepository(self.session).get_by_id(memory_id)
        if memory is None:
            return
        if str(memory.tenant_id) != payload.get("tenant_id"):
            return
        if str(memory.project_id) != payload.get("project_id"):
            return

        event_type = event.get("event_type")
        if event_type in ("memory.created", "memory.updated"):
            if memory.status == "deleted":
                await self.index.delete(memory.id)
            else:
                await self.index.index(memory)
                memory.status = "active"
                memory.qdrant_point_id = memory.id
                memory.updated_at = datetime.now(UTC)
        elif event_type == "memory.deleted":
            await self.index.delete(memory.id)
        await self.session.commit()
