import hashlib
import json
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal, TypeAlias

from pydantic import BaseModel, Field, model_validator


class ErrorCode(StrEnum):
    COLLECTION_NOT_FOUND = "COLLECTION_NOT_FOUND"
    COLLECTION_DISABLED = "COLLECTION_DISABLED"
    COLLECTION_EXISTS = "COLLECTION_EXISTS"


class AppError(Exception):
    def __init__(self, code: ErrorCode):
        self.code = code


class Text(BaseModel):
    type: Literal["text"] = "text"
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def hash_id(self):
        # 去重键：content + metadata 一起序列化，sort_keys 保证键序稳定。
        # metadata 不同则不去重（如 content 相同但 datetime 不同的会话各自保留）。
        payload = json.dumps(self.model_dump(), sort_keys=True, ensure_ascii=False)
        return hashlib.md5(payload.encode()).hexdigest()


class Image(BaseModel):
    """与 Text 平级的图片内容单元。url 与 path 必须且仅有一个非 None（path 为服务端本机可读路径）。"""

    type: Literal["image"] = "image"
    url: str | None = Field(default=None, description="http(s) 图片 URL")
    path: str | None = Field(default=None, description="服务端本机图片文件路径")
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_source(self):
        if (self.url is None) == (self.path is None):
            raise ValueError("url 与 path 必须且仅有一个非 None")
        return self

    @property
    def hash_id(self):
        payload = json.dumps(self.model_dump(), sort_keys=True, ensure_ascii=False)
        return hashlib.md5(payload.encode()).hexdigest()

    @property
    def content(self) -> str:
        """统一内容访问器：返回图片的模型输入串（url 或服务端本机 path）。"""
        return self.url or self.path


Document: TypeAlias = Annotated[Text | Image, Field(discriminator="type")]
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
