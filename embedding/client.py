import numpy as np
import httpx
import logging

logger = logging.getLogger(__name__)


class EmbeddingClient:
    def __init__(self, base_url: str):
        self._client = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=120)
        self._dims: int | None = None
        logger.info("EmbeddingClient connected to %s", base_url)

    async def encode(
        self, texts: list[str], hybrid: bool = False
    ) -> tuple[np.ndarray, list[dict] | None]:
        rsp = await self._client.post(
            "/embed",
            json={"texts": texts, "hybrid": hybrid},
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
