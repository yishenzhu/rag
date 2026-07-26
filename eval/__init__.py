"""RAG 评测模块。

Usage:
    from rag.eval import EvalRunner
    runner = EvalRunner("nfcorpus")
    await runner.setup()
    await runner.run_all()
"""

from .datasets import load_dataset, BEIR_DATASETS
from .runner import EvalRunner

__all__ = ["EvalRunner", "load_dataset", "BEIR_DATASETS"]
