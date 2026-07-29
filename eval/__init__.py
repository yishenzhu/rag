"""RAG 评测模块。

Usage:
    from rag.eval import EvalRunner

    runner = EvalRunner("nfcorpus", "eval")
    await runner.setup()
    await runner.run_all()
"""

import os

# 离线优先：默认走本地缓存，避免无网环境下的网络超时。
# 必须在 import datasets/huggingface_hub 之前设置——这两个库在 import 时一次性捕获该开关，
# 运行时再改 os.environ 无效。需要联网(首次)下载数据集/模型时，用 HF_HUB_OFFLINE=0 运行。
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from .datasets import load_dataset, BEIR_DATASETS
from .runner import EvalRunner

__all__ = [
    "EvalRunner",
    "load_dataset", "BEIR_DATASETS",
]
