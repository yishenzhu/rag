"""BEIR 数据集适配包。

from rag.eval.beir import BEIRDataset, BEIRMetric
"""

from .dataset import BEIR_DATASETS, BEIRDataset
from .metric import BEIRMetric

__all__ = [
    "BEIR_DATASETS",
    "BEIRDataset",
    "BEIRMetric",
]
