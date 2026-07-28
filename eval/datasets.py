"""BEIR 数据集加载。"""

import logging
import os

from beir.datasets.data_loader_hf import HFDataLoader

logger = logging.getLogger(__name__)

BEIR_DATASETS = [
    "scifact",
    "nfcorpus",
    "fiqa",
    "trec-covid",
    "arguana",
    "webis-touche2020",
    "cqadupstack",
    "quora",
    "dbpedia-entity",
    "scidocs",
    "fever",
    "climate-fever",
    "nq",
    "msmarco",
    "hotpotqa",
]


def load_dataset(dataset_name: str):
    logger.info("Loading BEIR dataset from HuggingFace: %s", dataset_name)

    os.environ.setdefault("HF_DATASETS_OFFLINE", "1")
    loader = HFDataLoader(hf_repo=f"BeIR/{dataset_name}")

    try:
        return loader.load()
    except Exception as exc:
        logger.warning(
            "Offline load failed for %s, trying one-time online download: %s",
            dataset_name,
            exc,
        )
        os.environ.pop("HF_DATASETS_OFFLINE", None)
        return loader.load()
