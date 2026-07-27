"""RAG 评测模块。

Usage:
    from rag.eval import EvalRunner, IngestRunner

    # 单 collection 评测
    runner = EvalRunner("nfcorpus", collections=["eval"])
    await runner.setup()
    await runner.run_all()

    # 多 collection 跨对比
    runner = EvalRunner("nfcorpus", collections=["eval_recursive", "eval_semantic"])
    await runner.setup()
    await runner.run_all()
"""

from .datasets import load_dataset, BEIR_DATASETS
from .ingest import IngestRunner
from .runner import EvalRunner

__all__ = [
    "EvalRunner", "IngestRunner",
    "load_dataset", "BEIR_DATASETS",
]
