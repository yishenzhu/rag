"""EvalRunner：核心评测流程。"""

import json
import logging
from pathlib import Path
from datetime import datetime

from beir.retrieval.evaluation import EvaluateRetrieval

from ..core import Config, SearchType, Document, auto_path, setup_logger
from ..engine import Pipeline
from .datasets import load_dataset
from .plotting import plot_single, plot_comparison

logger = logging.getLogger(__name__)


class EvalRunner:
    """BEIR 评测运行器。"""

    K_VALUES = [1, 10, 50, 100]
    COMBINATIONS = [
        (SearchType.DENSE, False),
        (SearchType.DENSE, True),
        (SearchType.HYBRID, False),
        (SearchType.HYBRID, True),
    ]

    def __init__(
        self,
        dataset_name: str,
        collection: str = "eval",
        threshold: float = 0.0,
        batch_size: int = 2048,
    ):
        self._dataset_name = dataset_name
        self._collection = collection
        self._threshold = threshold
        self._batch_size = batch_size
        self._pipeline: Pipeline | None = None
        self._corpus: list | None = None
        self._queries: list | None = None
        self._qrels: dict | None = None

    # ── 加载 ──────────────────────────────────────────────

    async def setup(self):
        self._corpus, self._queries, self._qrels = load_dataset(self._dataset_name)
        logger.info(
            "Dataset loaded: %d corpus, %d queries, %d qrels",
            len(self._corpus),
            len(self._queries),
            len(self._qrels),
        )
        conf = Config.load()
        setup_logger(conf.log)
        self._pipeline = await Pipeline(conf.rag).setup()
        return self

    # ── 运行单项 ──────────────────────────────────────────

    async def run_single(
        self,
        search_type: SearchType,
        rerank: bool = False,
        skip_ingest: bool = False,
    ) -> dict:
        logger.info(
            "Running: search_type=%s, rerank=%s", search_type.value, rerank
        )
        await self._ingest_if_needed(skip_ingest)

        metrics = await self._evaluate(search_type, rerank)
        label = self._make_label(search_type, rerank)

        report = {
            "dataset": self._dataset_name,
            "collection": self._collection,
            "search_type": search_type.value,
            "rerank": rerank,
            "num_queries": len(self._queries),
            "num_corpus": len(self._corpus),
            "metrics": metrics,
        }

        print(json.dumps(report, ensure_ascii=False, indent=2))
        self._save_json(report, label)
        plot_single(report, label)
        return report

    # ── 运行全部 ──────────────────────────────────────────

    async def run_all(self, skip_ingest: bool = False):
        reports: list[dict] = []

        for i, (search_type, rerank) in enumerate(self.COMBINATIONS):
            sep = "=" * 60
            print(
                f"\n{sep}\n"
                f"Combination {i + 1}/{len(self.COMBINATIONS)}: "
                f"search_type={search_type.value}, rerank={rerank}\n"
                f"{sep}"
            )
            report = await self.run_single(
                search_type=search_type,
                rerank=rerank,
                skip_ingest=skip_ingest or i > 0,
            )
            reports.append(report)

        plot_comparison(reports, self._dataset_name)

    # ── 内部方法 ──────────────────────────────────────────

    def _make_label(self, search_type: SearchType, rerank: bool) -> str:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        return (
            f"{self._dataset_name}_{search_type.value}_"
            f"{'rerank' if rerank else 'no_rerank'}_{ts}"
        )

    async def _ingest_if_needed(self, skip: bool):
        if skip or not self._corpus:
            return

        logger.info("Ingesting corpus into collection '%s'...", self._collection)
        documents = [
            Document(
                content=f"{row['title']}\n{row['text']}",
                metadata={"doc_id": row["id"]},
            )
            for row in self._corpus
        ]
        total = len(documents)
        bs = self._batch_size
        for i in range(0, total, bs):
            batch = documents[i : i + bs]
            print(
                f"  Batch {i // bs + 1}/{(total + bs - 1) // bs} "
                f"({len(batch)} docs)"
            )
            await self._pipeline._knowledge.ingest(
                self._collection, batch, chunk=False
            )
        logger.info("Ingest complete: %d documents", total)

    async def _evaluate(
        self, search_type: SearchType, rerank: bool
    ) -> dict[str, float]:
        metrics: dict[str, float] = {}
        for k in self.K_VALUES:
            results: dict[str, dict[str, float]] = {}
            for row in self._queries:
                qid, query = row["id"], row["text"]
                hits = await self._pipeline._knowledge.search(
                    self._collection, [query], k,
                    self._threshold, search_type, rerank,
                )
                results[qid] = {
                    r.payload.metadata["doc_id"]: r.score for r in hits
                }
            ndcg, _map, recall, precision = EvaluateRetrieval.evaluate(
                self._qrels, results, [k]
            )
            mrr = EvaluateRetrieval.evaluate_custom(
                self._qrels, results, [k], metric="mrr"
            )
            metrics.update({**ndcg, **_map, **recall, **precision, **mrr})
        return metrics

    @staticmethod
    def _save_json(report: dict, label: str):
        path = auto_path(f"data/{label}.json")
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        logger.info("Report saved: %s", path)
