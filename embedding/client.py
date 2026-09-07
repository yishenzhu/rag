import logging

import httpx
import numpy as np

logger = logging.getLogger(__name__)


class EmbeddingClient:
    def __init__(self, base_url: str, timeout: float = 120.0):
        self._client = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout)
        self._dims: int | None = None
        logger.info("EmbeddingClient connected to %s", base_url)

    async def encode(
        self,
        texts: list[str] | None = None,
        images: list[str] | None = None,
        hybrid: bool = False,
    ) -> tuple[np.ndarray, list[dict] | None]:
        """编码文本与图片，返回 (dense, sparse)。

        texts 为文本原文；images 为 http(s) URL 或 dataURI base64 字符串，
        dense 行序 = texts + images。sparse 仅在 BGE-M3 且 hybrid=True 时非 None，
        多模态后端恒为 None。
        """
        rsp = await self._client.post(
            "/embed",
            json={
                "texts": texts or [],
                "images": images or [],
                "hybrid": hybrid,
            },
        )
        rsp.raise_for_status()
        data = rsp.json()

        dense = np.array(data["dense_vecs"], dtype=np.float32)
        sparse = data.get("sparse_vectors")
        return dense, sparse

    async def get_dims(self) -> int:
        if self._dims is None:
            rsp = await self._client.get("/dims")
            rsp.raise_for_status()
            self._dims = rsp.json()["dims"]
        return self._dims

    async def aclose(self) -> None:
        await self._client.aclose()
