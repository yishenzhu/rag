"""评测抽象：数据集与指标适配器接口。

EvalRunner 只依赖这两个抽象，不绑定具体数据源与指标实现：
- EvalDataset 负责提供 corpus / queries / qrels
- Metric 负责按 qrels 计算给定检索结果的指标
"""

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class EvalDataset(Protocol):
    """评测数据集。corpus/queries 为逐行 dict（含 id 字段），qrels 为 {qid: {doc_id: rel}}。"""

    name: str

    def load(self) -> tuple[Any, Any, dict]:
        """返回 (corpus, queries, qrels)。"""
        ...


@runtime_checkable
class Metric(Protocol):
    """检索指标。results 为 {qid: {doc_id: score}}，score 越大越相关。"""

    def evaluate(
        self, qrels: dict, results: dict, k_values: list[int]
    ) -> dict[str, float]:
        """返回指标名到分值的映射，如 {"NDCG@10": 0.42}。"""
        ...
