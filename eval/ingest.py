"""IngestRunner：独立的语料导入运行器。"""

import logging

from ..core import Config, Document, setup_logger
from ..engine import Pipeline
from .datasets import load_dataset

logger = logging.getLogger(__name__)


class IngestRunner:
    """只负责将 BEIR 数据集导入到指定 collection，不涉及评测。"""

    def __init__(
        self,
        dataset_name: str,
        collection: str = "eval",
        *,
        chunker_type: str = "none",
        chunk_size: int = 512,
        chunk_overlap: int = 64,
        batch_size: int = 512,
    ):
        self._dataset_name = dataset_name
        self._collection = collection
        self._chunker_type = chunker_type
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap
        self._batch_size = batch_size
        self._pipeline: Pipeline | None = None

    async def setup(self):
        conf = Config.load()
        setup_logger(conf.log)
        self._pipeline = await Pipeline(conf.rag).setup()

        # 确保 collection 已注册（不存在则自动创建）
        await self._ensure_collection()
        return self

    async def run(self):
        corpus, _, _ = load_dataset(self._dataset_name)
        logger.info("Ingesting %d docs → '%s' (chunker=%s)",
                     len(corpus), self._collection, self._chunker_type)

        documents = [
            Document(
                content=f"{row['title']}\n{row['text']}",
                metadata={"doc_id": row["id"]},
            )
            for row in corpus
        ]

        total = len(documents)
        bs = self._batch_size
        for i in range(0, total, bs):
            batch = documents[i : i + bs]
            print(f"  Batch {i // bs + 1}/{(total + bs - 1) // bs} "
                  f"({len(batch)} docs)")
            await self._pipeline._knowledge.ingest(
                self._collection,
                batch,
                chunker_type=self._chunker_type,
                chunk_size=self._chunk_size,
                chunk_overlap=self._chunk_overlap,
            )

        logger.info("Ingest complete: %d docs → %s", total, self._collection)

    async def _ensure_collection(self):
        ns_name = self._pipeline._knowledge.namespaced(self._collection)
        if ns_name in self._pipeline._knowledge._collections:
            return
        logger.info("Creating collection '%s'...", self._collection)
        await self._pipeline._knowledge.create({
            "name": self._collection,
            "enabled": True,
            "hybrid": True,
        })
