from datetime import datetime
from .base import Registry
from ..core import Memory


class MemoryBank(Registry):
    def _normalize(self, memories: list[Memory] | list[str]) -> list[Memory]:
        if not memories:
            return []
        if isinstance(memories[0], str):
            return [Memory(content=m) for m in memories]
        return memories

    async def add(
        self, name: str, memories: list[Memory] | list[str], dup_threshold: float = 0.95
    ):
        collection = self.collection(name)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        items = self._normalize(memories)
        for m in items:
            m.metadata["created_at"] = now

        await collection.insert(items, dup_threshold)
