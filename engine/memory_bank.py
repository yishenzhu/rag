from datetime import datetime

from ..core import Memory
from .registry import CollectionRegistry


class MemoryBank(CollectionRegistry):
    def _normalize(self, memories: list[Memory] | list[str]) -> list[Memory]:
        if not memories:
            return []
        if isinstance(memories[0], str):
            return [Memory(content=m) for m in memories]
        return memories

    async def add_memories(
        self, name: str, memories: list[Memory] | list[str], dup_threshold: float = 0.95
    ):
        collection = self.get_collection(name)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        items = self._normalize(memories)
        for m in items:
            m.metadata["created_at"] = now

        await collection.upsert(items, dup_threshold)
