from datetime import datetime
from ..core import Document, Image, Text
from .chunker import RecursiveChunker, SemanticChunker, MarkdownChunker
from .base import Registry


class KnowledgeBase(Registry):
    async def ingest(
        self,
        name: str,
        documents: list[Document],
        chunk_size: int | None = None,
        chunk_overlap: int | None = None,
        chunker_type: str | None = None,
    ):
        collection = self.collection(name)

        # 图片不可切分（content 是 url/path），仅文本参与分块
        text_docs = [d for d in documents if isinstance(d, Text)]
        image_docs = [d for d in documents if isinstance(d, Image)]

        if chunker_type is None:
            texts = text_docs
        elif chunker_type == "semantic":
            chunker = SemanticChunker(
                chunk_size=chunk_size or 512,
                embed_client=self._embed,
            )
            texts = [
                chunk
                for doc in text_docs
                for chunk in await chunker.split(doc)
            ]
        elif chunker_type == "markdown":
            chunker = MarkdownChunker(chunk_size or 512, chunk_overlap)
            texts = [chunk for doc in text_docs for chunk in chunker.split(doc)]
        else:
            chunker = RecursiveChunker(chunk_size, chunk_overlap)
            texts = [chunk for doc in text_docs for chunk in chunker.split(doc)]

        items = texts + image_docs
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for item in items:
            item.metadata["indexed_at"] = now

        await collection.insert(items)
