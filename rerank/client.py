import httpx
import time
import logging

logger = logging.getLogger(__name__)


class RerankClient:
    """Rerank 客户端 —— 通过 HTTP 调用模型推理服务"""

    def __init__(self, base_url: str):
        self._client = httpx.Client(base_url=base_url.rstrip("/"), timeout=120)
        logger.info("RerankClient connected to %s", base_url)

    def rerank(self, queries: list[str], texts: list[list[str]]) -> list[list[float]]:
        """统一 rerank 接口：每个 query 独立分组，返回 per-query scores。"""
        rsp = self._client.post(
            "/rerank",
            json={"queries": queries, "texts": texts},
        )
        rsp.raise_for_status()
        return rsp.json()["scores"]

    def close(self) -> None:
        self._client.close()
