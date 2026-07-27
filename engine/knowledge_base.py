from datetime import datetime
from ..core import Document
from .chunker import RecursiveChunker, SemanticChunker
from .base import Registry


class KnowledgeBase(Registry):
    async def ingest(
        self,
        name: str,
        documents: list[Document],
        chunk_size: int | None = None,
        chunk_overlap: int | None = None,
        chunker_type: str = "recursive",
    ):
        collection = self.collection(name)

        if chunker_type == "none":
            texts = documents
        elif chunker_type == "semantic":
            chunker = SemanticChunker(
                chunk_size=chunk_size or 512,
                embed_client=self._embedding,
            )
            texts = [chunk for doc in documents for chunk in chunker.split(doc)]
        else:
            chunker = RecursiveChunker(chunk_size, chunk_overlap)
            texts = [chunk for doc in documents for chunk in chunker.split(doc)]

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for t in texts:
            t.metadata["indexed_at"] = now

        await collection.insert(texts)
