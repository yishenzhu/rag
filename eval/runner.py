"""EvalRunner：纯评测流程（不负责 ingest，不负责绘图）。

通过注入 EvalDataset + Metric 适配器，与具体数据源/指标解耦。
必须显式传入数据集对象与指标对象，不绑定任何具体数据源。
"""

import json
import logging
from pathlib import Path
from datetime import datetime

import httpx

from ..core import Config, SearchType, auto_path, setup_logger
from .base import EvalDataset, Metric

logger = logging.getLogger(__name__)


class EvalRunner:
    """通用评测运行器。假定 collection 已存在并已导入数据。

    在单个 collection 上跑全部 4 种检索组合；只输出 JSON 报告，绘图由 plotting.py 单独完成。
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
        dataset: EvalDataset,
        metric: Metric,
        collection: str = "eval",
        threshold: float = 0.0,
        host: str = "http://localhost:8001",
    ):
        self._dataset = dataset
        self._metric = metric
        self._collection = collection
        self._threshold = threshold
        self._host = host.rstrip("/")
        self._corpus: list = []
        self._queries: list[dict] = []
        self._qrels: dict = {}

    # ── 加载 ──────────────────────────────────────────────

    async def setup(self):
        self._corpus, self._queries, self._qrels = self._dataset.load()
        logger.info(
            "Dataset loaded: %d corpus, %d queries, %d qrels",
            len(self._corpus),
            len(self._queries),
            len(self._qrels),
        )
        conf = Config.load()
        setup_logger(conf.log)

        # 验证 RAG 服务可用
        async with httpx.AsyncClient(timeout=10) as client:
            rsp = await client.get(f"{self._host}/health")
            rsp.raise_for_status()
        logger.info("RAG service is ready at %s", self._host)
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
            "dataset": self._dataset.name,
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

    # ── 运行全部（4 种检索组合）────────────────────────────

    async def run_all(self) -> tuple[list[dict], list[str]]:
        """返回 (all_reports, paths)。在单个 collection 上跑全部 4 种检索组合。"""
        all_reports: list[dict] = []
        paths: list[str] = []

        sep = "=" * 60
        print(f"\n{sep}\n  Collection: {self._collection}\n{sep}")
        for i, (search_type, rerank) in enumerate(self.COMBINATIONS):
            print(
                f"\n  [{self._collection}] Combo {i + 1}/{len(self.COMBINATIONS)}: "
                f"{search_type.value}{' + Rerank' if rerank else ''}"
            )
            report, json_path = await self.run_single(
                self._collection, search_type, rerank
            )
            all_reports.append(report)
            paths.append(json_path)

        return all_reports, paths

    # ── 内部方法 ──────────────────────────────────────────

    async def _evaluate(
        self, collection: str, search_type: SearchType, rerank: bool
    ) -> dict[str, float]:
        metrics: dict[str, float] = {}
        url = f"{self._host}/knowledge/search"

        async with httpx.AsyncClient(timeout=300) as client:
            for k in self.K_VALUES:
                results: dict[str, dict[str, float]] = {}
                for row in self._queries:
                    qid, query = row["id"], row["text"]
                    payload = {
                        "collection": collection,
                        "queries": [query],
                        "top_k": k,
                        "threshold": self._threshold,
                        "search_type": search_type.value,
                        "rerank": rerank,
                    }
                    rsp = await client.post(url, json=payload)
                    rsp.raise_for_status()
                    data = rsp.json()

                    if not data.get("success"):
                        logger.error("Search failed: %s", data)
                        raise RuntimeError(f"Search failed: {data}")

                    hits = data.get("results", [])
                    # 检索结果已按相关性降序，而 pytrec_eval 按值降序取序，
                    # 故用递减分数表达名次（第 1 名分最高）；无 doc_id 的命中跳过。
                    n = len(hits)
                    results[qid] = {
                        r["payload"]["metadata"].get("doc_id"): n - rank
                        for rank, r in enumerate(hits)
                        if r["payload"]["metadata"].get("doc_id")
                    }

                # 指标计算交给注入的 Metric 适配器
                metrics.update(self._metric.evaluate(self._qrels, results, [k]))
        return metrics

    def _save_json(
        self, report: dict, collection: str, search_type: SearchType, rerank: bool
    ) -> str:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        name = (
            f"{self._dataset.name}_{collection}_{search_type.value}_"
            f"{'rerank' if rerank else 'no_rerank'}_{ts}"
        )
        path = auto_path(f"data/{name}.json")
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        logger.info("Report saved: %s", path)
        return path
