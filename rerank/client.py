from sentence_transformers import CrossEncoder
import torch
import time
import logging
from ..core import RerankConfig, Config

logger = logging.getLogger(__name__)


class RerankClient:
    def __init__(self, conf: RerankConfig):
        self._batch_size = conf.batch_size
        self._model = CrossEncoder(
            conf.model,
            device="cuda" if torch.cuda.is_available() else "cpu",
            max_length=512,
            model_kwargs={"torch_dtype": torch.float16},
        )

    def rerank(self, query: str, texts: list[str]) -> list[float]:
        pairs = [(query, doc) for doc in texts]
        t0 = time.perf_counter()
        scores = self._model.predict(pairs, batch_size=self._batch_size).tolist()
        elapsed = time.perf_counter() - t0
        logger.info(
            "Reranked %d docs in %.3fs (batch=%d)",
            len(texts),
            elapsed,
            self._batch_size,
        )
        return scores


if __name__ == "__main__":
    conf = Config.load()
    client = RerankClient(conf.rag.rerank)

    query = "什么是机器学习"
    docs = [
        "机器学习是人工智能的一个分支，它使计算机能够从数据中学习。",
        "今天天气不错，适合出门散步。",
        "深度学习是机器学习的子集，使用多层神经网络来学习数据的表示。",
    ]

    scores = client.rerank(query, docs)
    ranked = sorted(zip(docs, scores), key=lambda x: x[1], reverse=True)

    print(f"Query: {query}\n")
    for doc, score in ranked:
        print(f"  [{score:.4f}] {doc}")
