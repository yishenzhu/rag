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
    """加载 BEIR 数据集（corpus + queries + qrels）。

    离线模式由进程启动时的 ``HF_HUB_OFFLINE`` 控制（eval 包导入时默认置 1）。
    数据集未缓存时，需以 ``HF_HUB_OFFLINE=0`` 重新运行以联网下载并写入缓存；
    之后的运行即可在离线模式下纯缓存命中。
    """
    logger.info("Loading BEIR dataset from HuggingFace: %s", dataset_name)
    return HFDataLoader(hf_repo=f"BeIR/{dataset_name}").load()


def load_corpus(dataset_name: str):
    """仅加载 BEIR 数据集的语料（不加载 queries/qrels），用于导入。"""
    logger.info("Loading BEIR corpus from HuggingFace: %s", dataset_name)
    return HFDataLoader(hf_repo=f"BeIR/{dataset_name}").load_corpus()
