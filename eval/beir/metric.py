"""BEIR 指标层：实现 eval.base.Metric。

用 beir 的 EvaluateRetrieval 计算 nDCG / MAP / Recall / Precision / MRR。
"""

from __future__ import annotations

from beir.retrieval.evaluation import EvaluateRetrieval

from ..base import Metric


class BEIRMetric(Metric):
    """BEIR 指标适配器。results 为 {qid: {doc_id: score}}，score 越大越相关。"""

    def evaluate(
        self, qrels: dict, results: dict, ks: list[int]
    ) -> dict[str, float]:
        ndcg, _map, recall, precision = EvaluateRetrieval.evaluate(qrels, results, ks)
        mrr = EvaluateRetrieval.evaluate_custom(qrels, results, ks, metric="mrr")
        return {**ndcg, **_map, **recall, **precision, **mrr}
