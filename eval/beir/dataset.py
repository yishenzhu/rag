"""BEIR 数据集适配层：实现 eval.base.EvalDataset。"""

from beir.datasets.data_loader_hf import HFDataLoader

from ...core import Text
from ..base import EvalDataset

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


class BEIRDataset(EvalDataset):
    """BEIR 数据集适配器。

    load() 返回 (docs, queries, qrels)：docs 为 Document 列表，
    queries 为 [{"id", "text"}]，qrels 为 {qid: {doc_id: rel}}。
    """

    def __init__(self, name: str, split: str = "test"):
        self.name = name
        self._split = split

    def load(self):
        corpus, queries, qrels = HFDataLoader(
            hf_repo=f"BeIR/{self.name}"
        ).load(split=self._split)
        docs = [self._to_text(row) for row in corpus]
        query_list = [{"id": q["id"], "text": q["text"]} for q in queries]
        return docs, query_list, qrels

    def load_corpus(self) -> list[Text]:
        """仅加载语料并转成 Text（供 ingest 使用）。"""
        corpus = HFDataLoader(hf_repo=f"BeIR/{self.name}").load_corpus()
        return [self._to_text(row) for row in corpus]

    @staticmethod
    def _to_text(row: dict) -> Text:
        return Text(
            content=f"{row['title']}\n{row['text']}",
            metadata={"doc_id": row["id"]},
        )
