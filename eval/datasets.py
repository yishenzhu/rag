"""BEIR 数据集加载。"""

import logging
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
    loader = HFDataLoader(hf_repo=f"BeIR/{dataset_name}")
    corpus, queries, qrels = loader.load()
    return corpus, queries, qrels
