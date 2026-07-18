from typing import Any
from qdrant_client import AsyncQdrantClient
from collections import defaultdict
from qdrant_client.http import models

DENSE_VECTOR_NAME = "dense"
SPARSE_VECTOR_NAME = "sparse"


class VectorStore:
    def __init__(
        self,
        name: str,
        client: AsyncQdrantClient,
    ):
        self._name = name
        self._client = client
        self._dims = None

    async def connect(self):
        if not self._dims:
            info = await self._client.get_collection(self._name)
            self._dims = info.config.params.vectors[DENSE_VECTOR_NAME].size
            self._metadata = info.config.metadata

    @property
    def metadata(self) -> dict[str, Any]:
        return self._metadata

    @property
    def dims(self) -> int:
        return self._dims

    @classmethod
    def to_filter(cls, filters: dict[str, Any]) -> models.Filter:
        conditions = []
        for key, value in filters.items():
            conditions.append(
                models.FieldCondition(
                    key=key,
                    match=models.MatchValue(value=value),
                )
            )
        return models.Filter(must=conditions)

    async def insert(
        self,
        payloads: list[dict[str, Any]],
        ids: list[str],
        dense_vectors: list[list[float]],
        sparse_vectors: list[dict] | None = None,
        dup_threshold: float | None = None,
    ):
        indices = list(range(len(ids)))
        if dup_threshold:
            requests = [
                models.QueryRequest(
                    query=dv,
                    using=DENSE_VECTOR_NAME,
                    limit=1,
                    score_threshold=dup_threshold,
                )
                for dv in dense_vectors
            ]

            responses = await self._client.query_batch_points(self._name, requests)
            indices = [i for i, rsp in enumerate(responses) if len(rsp.points) == 0]

            if len(indices) < len(ids):
                ids = [ids[i] for i in indices]
                dense_vectors = [dense_vectors[i] for i in indices]
                payloads = [payloads[i] for i in indices]
                if sparse_vectors:
                    sparse_vectors = [sparse_vectors[i] for i in indices]

        if len(indices) == 0:
            return

        points = []
        for i in indices:
            vector: dict[str, Any] = {DENSE_VECTOR_NAME: dense_vectors[i]}
            if sparse_vectors:
                vector[SPARSE_VECTOR_NAME] = models.SparseVector(**sparse_vectors[i])
            points.append(
                models.PointStruct(id=ids[i], vector=vector, payload=payloads[i])
            )

        await self._client.upsert(
            collection_name=self._name,
            points=points,
        )

    async def query(
        self,
        dense_vectors: list[list[float]],
        top_k: int,
        threshold: float,
        filters: dict[str, Any] | None = None,
        sparse_vectors: list[dict] | None = None,
    ):
        filter_ = self.__class__.to_filter(filters) if filters else None

        if sparse_vectors is None:
            requests = [
                models.QueryRequest(
                    query=dv,
                    using=DENSE_VECTOR_NAME,
                    limit=top_k,
                    score_threshold=threshold,
                    with_payload=True,
                    filter=filter_,
                )
                for dv in dense_vectors
            ]
        else:
            requests = []
            for dv, sv in zip(dense_vectors, sparse_vectors):
                sv = models.SparseVector(**sv)
                requests.append(
                    models.QueryRequest(
                        prefetch=[
                            models.Prefetch(
                                query=dv,
                                using=DENSE_VECTOR_NAME,
                                limit=top_k,
                            ),
                            models.Prefetch(
                                query=sv, using=SPARSE_VECTOR_NAME, limit=top_k
                            ),
                        ],
                        query=models.FusionQuery(fusion=models.Fusion.RRF),
                        limit=top_k,
                        score_threshold=threshold,
                        with_payload=True,
                        filter=filter_,
                    )
                )

        responses = await self._client.query_batch_points(self._name, requests)
        return self.merge(responses)

    def merge(self, responses: list[models.QueryResponse], k=60):
        if len(responses) == 1:
            return responses[0].points

        score_map = defaultdict(float)
        point_map = {}
        for rsp in responses:
            for rank, point in enumerate(rsp.points):
                score_map[point.id] += 1.0 / (k + rank)
                point_map[point.id] = point

        sorted_ids = sorted(score_map.items(), key=lambda x: x[1], reverse=True)
        return [point_map[id] for id, _ in sorted_ids]

    async def create(self, dims: int, metadata: dict[str, Any] | None = None):
        self._dims = dims
        self._metadata = metadata
        await self._client.create_collection(
            collection_name=self._name,
            vectors_config={
                DENSE_VECTOR_NAME: models.VectorParams(
                    size=self._dims, distance=models.Distance.COSINE
                )
            },
            sparse_vectors_config={SPARSE_VECTOR_NAME: models.SparseVectorParams()},
            metadata=self._metadata,
        )

    async def list_all(self):
        all_points = []
        offset = None

        while True:
            points, offset = await self._client.scroll(
                collection_name=self._name,
                limit=64,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            all_points.extend(points)

            if offset is None:
                break
        return all_points
