import logging

from mcp.server.fastmcp import FastMCP
from pydantic import Field
from starlette.requests import Request
from starlette.responses import JSONResponse

from .core import CollectionInfo, Config, FilterRule, SearchResult
from .engine import Pipeline

logger = logging.getLogger(__name__)


async def main():
    conf = Config.load()
    pipeline = await Pipeline(conf.rag).setup()

    mcp = FastMCP("RAG MCP", host=conf.mcp.host, port=conf.mcp.port)

    @mcp.tool(description="添加用户记忆，用户要求记住或暴露用户重要信息时使用")
    async def add_memory(memories: list[str]) -> bool:
        await pipeline._memory.add("user", memories)
        return True

    @mcp.tool(description="搜索用户记忆")
    async def search_memory(queries: list[str]) -> list[SearchResult]:
        return await pipeline._memory.search("user", queries, rerank=True)

    @mcp.tool(description="列出所有知识库")
    async def list_knowledge() -> list[CollectionInfo]:
        return pipeline._knowledge.list_collections(True, False)

    @mcp.tool(description="搜索指定知识库")
    async def search_knowledge(
        queries: list[str] = Field(description="搜索查询列表"),
        collection: str = Field(description="知识库名"),
        top_k: int = Field(default=5, description="返回条数"),
        filters: list[FilterRule] | None = Field(
            default=None, description="元数据过滤规则列表"
        ),
    ) -> list[SearchResult]:
        return await pipeline._knowledge.search(
            collection, queries, top_k=top_k, rerank=True, filters=filters
        )

    logger.info("MCP server starting on %s:%d", conf.mcp.host, conf.mcp.port)

    @mcp.custom_route("/health", methods=["GET"])
    async def health(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "service": "rag-mcp"})

    await mcp.run_streamable_http_async()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
