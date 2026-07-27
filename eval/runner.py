"""EvalRunner：纯评测流程（不负责 ingest，不负责绘图）。"""

import json
import logging
from pathlib import Path
from datetime import datetime

from beir.retrieval.evaluation import EvaluateRetrieval

from ..core import Config, SearchType, auto_path, setup_logger
from ..engine import Pipeline
from .datasets import load_dataset

logger = logging.getLogger(__name__)


class EvalRunner:
    """BEIR 评测运行器。假定 collection 已存在并已导入数据。

    传入多个 collection 时会在同一份 queries/qrels 上对比检索效果。
    只输出 JSON 报告，绘图由 plotting.py 单独完成。
    """

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
        collections: list[str] | None = None,
        threshold: float = 0.0,
    ):
        self._dataset_name = dataset_name
        self._collections = collections or ["eval"]
        self._threshold = threshold
        self._pipeline: Pipeline | None = None
        self._corpus: list | None = None
        self._queries: list | None = None
        self._qrels: dict | None = None

    # ── 加载 ──────────────────────────────────────────────

    async def setup(self):
        self._corpus, self._queries, self._qrels = load_dataset(self._dataset_name)
        logger.info(
            "Dataset loaded: %d corpus, %d queries, %d qrels",
            len(self._corpus), len(self._queries), len(self._qrels),
        )
        conf = Config.load()
        setup_logger(conf.log)
        self._pipeline = await Pipeline(conf.rag).setup()
        return self

    # ── 单 collection × 单策略 ─────────────────────────────

    async def run_single(
        self,
        collection: str,
        search_type: SearchType,
        rerank: bool = False,
    ) -> tuple[dict, str]:
        """返回 (report, json_path)。"""
        metrics = await self._evaluate(collection, search_type, rerank)

        report = {
            "dataset": self._dataset_name,
            "collection": collection,
            "search_type": search_type.value,
            "rerank": rerank,
            "num_queries": len(self._queries),
            "num_corpus": len(self._corpus),
            "metrics": metrics,
        }

        print(json.dumps(report, ensure_ascii=False, indent=2))
        json_path = self._save_json(report, collection, search_type, rerank)
        return report, json_path

    # ── 运行全部（多 collection 跨对比）────────────────────

    async def run_all(self) -> tuple[list[dict], dict[str, list[str]]]:
        """返回 (all_reports, paths_by_collection)。"""
        all_reports: list[dict] = []
        paths_by_col: dict[str, list[str]] = {}

        for ci, collection in enumerate(self._collections):
            sep = "=" * 60
            print(f"\n{sep}\n  Collection {ci + 1}/{len(self._collections)}: {collection}\n{sep}")

            col_paths: list[str] = []
            for i, (search_type, rerank) in enumerate(self.COMBINATIONS):
                print(
                    f"\n  [{collection}] Combo {i + 1}/4: "
                    f"{search_type.value}{' + Rerank' if rerank else ''}"
                )
                report, json_path = await self.run_single(collection, search_type, rerank)
                all_reports.append(report)
                col_paths.append(json_path)
            paths_by_col[collection] = col_paths

        return all_reports, paths_by_col

    # ── 内部方法 ──────────────────────────────────────────

    async def _evaluate(
        self, collection: str, search_type: SearchType, rerank: bool
    ) -> dict[str, float]:
        metrics: dict[str, float] = {}
        for k in self.K_VALUES:
            results: dict[str, dict[str, float]] = {}
            for row in self._queries:
                qid, query = row["id"], row["text"]
                hits = await self._pipeline._knowledge.search(
                    collection, [query], k,
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

    def _save_json(
        self, report: dict, collection: str, search_type: SearchType, rerank: bool
    ) -> str:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        name = (
            f"{self._dataset_name}_{collection}_{search_type.value}_"
            f"{'rerank' if rerank else 'no_rerank'}_{ts}"
        )
        path = auto_path(f"data/{name}.json")
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        logger.info("Report saved: %s", path)
        return path
