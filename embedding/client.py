import torch
import numpy as np
from FlagEmbedding import BGEM3FlagModel
from ..core import EmbeddingConfig


class EmbeddingClient:
    def __init__(self, conf: EmbeddingConfig):
        self._conf = conf
        self._device = "cuda" if torch.cuda.is_available() else "cpu"
        self._model = BGEM3FlagModel(
            conf.model,
            devices=self._device,
            batch_size=conf.batch_size,
        )

    def encode(
        self, texts: list[str], hybrid: bool = False
    ) -> tuple[np.ndarray, list[dict] | None]:
        output = self._model.encode(texts, return_dense=True, return_sparse=hybrid)
        sparse_vectors = (
            [
                {
                    "indices": [int(k) for k in lw],
                    "values": [float(v) for v in lw.values()],
                }
                for lw in output["lexical_weights"]
            ]
            if hybrid
            else None
        )
        return output["dense_vecs"], sparse_vectors

    @property
    def dims(self) -> int:
        return self._model.model.model.config.hidden_size
