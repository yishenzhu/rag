import hashlib
from datetime import datetime
from enum import StrEnum
from typing import Any, TypeAlias

from pydantic import BaseModel, Field


class ErrorCode(StrEnum):
    COLLECTION_NOT_FOUND = "COLLECTION_NOT_FOUND"
    COLLECTION_DISABLED = "COLLECTION_DISABLED"
    COLLECTION_EXISTS = "COLLECTION_EXISTS"


class AppError(Exception):
    def __init__(self, code: ErrorCode):
        self.code = code


class Text(BaseModel):
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def hash_id(self):
        return hashlib.md5(self.content.encode()).hexdigest()


Document: TypeAlias = Text
Chunk: TypeAlias = Text
Memory: TypeAlias = Text


class CreateReq(BaseModel):
    name: str
    description: str | None = None
    enabled: bool = True
    hybrid: bool = True
    fields: list[dict[str, str]] = Field(default_factory=list)


class CreateRsp(BaseModel):
    collection: str
    success: bool = False
    error_code: ErrorCode | None = None


class DeleteRsp(BaseModel):
    collection: str
    success: bool = False
    error_code: ErrorCode | None = None


class CollectionInfo(CreateReq):
    created_at: str = Field(
        default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )
    # 该库可用的 metadata 字段 schema，供 AI 构造过滤规则
    fields: list[dict[str, str]] = Field(default_factory=list)


class CollectionBriefInfo(BaseModel):
    name: str
    description: str | None = None
    fields: list[dict[str, str]] = Field(default_factory=list)


class IngestReq(BaseModel):
    collection: str
    documents: list[Document]
    chunk_size: int | None = None
    chunk_overlap: int | None = None
    chunker_type: str | None = None  # None=不分块, recursive, semantic, markdown


class IngestRsp(BaseModel):
    collection: str
    success: bool = False
    count: int = 0
    error_code: ErrorCode | None = None


class SearchType(StrEnum):
    DENSE = "dense"
    HYBRID = "hybrid"


class FilterOperator(StrEnum):
    EQ = "eq"
    IN = "in"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    EXISTS = "exists"


class FilterRule(BaseModel):
    """一条元数据过滤规则。"""

    key: str = Field(description="字段名")
    operator: FilterOperator = Field(
        default=FilterOperator.EQ, description="过滤操作符"
    )
    value: Any | None = Field(default=None, description="匹配值")


class SearchResult(BaseModel):
    payload: Text
    score: float = 0.0


class SearchReq(BaseModel):
    collection: str
    queries: list[str]
    top_k: int = 5
    threshold: float = 0.1
    search_type: SearchType = SearchType.DENSE
    rerank: bool = False
    filters: list[FilterRule] | None = None


class SearchRsp(BaseModel):
    results: list[SearchResult]
    success: bool = False
    error_code: ErrorCode | None = None


class ListRsp(BaseModel):
    collections: list[CollectionInfo | CollectionBriefInfo]
    count: int
