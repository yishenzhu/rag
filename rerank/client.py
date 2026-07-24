import httpx
import time
import logging

logger = logging.getLogger(__name__)


class RerankClient:
    """Rerank 客户端 —— 通过 HTTP 调用模型推理服务"""

    def __init__(self, base_url: str):
        self._client = httpx.Client(base_url=base_url.rstrip("/"), timeout=120)
        logger.info("RerankClient connected to %s", base_url)

    def rerank(self, query: str, texts: list[str]) -> list[float]:
        t0 = time.perf_counter()
        rsp = self._client.post(
            "/rerank",
            json={"query": query, "texts": texts},
        )
        rsp.raise_for_status()
        data = rsp.json()
        elapsed = time.perf_counter() - t0
        logger.info(
            "Reranked %d docs in %.3fs",
            len(texts),
            elapsed,
        )
        return data["scores"]

    def close(self) -> None:
        self._client.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8002")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    client = RerankClient(args.url)

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
