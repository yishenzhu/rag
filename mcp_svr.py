import logging
from mcp.server.fastmcp import FastMCP
from pydantic import Field
from starlette.requests import Request
from starlette.responses import JSONResponse
from .core import Config, SearchResult, CollectionInfo, CollectionBriefInfo
from .engine import Pipeline

logger = logging.getLogger(__name__)


async def main():
    conf = Config.load()
    pipeline = await Pipeline(conf.rag).setup()

    mcp = FastMCP("RAG MCP", host=conf.mcp.host, port=conf.mcp.port)

    @mcp.tool(description="添加用户记忆，当用户明确要求记住或对话中暴露重要信息时使用")
    async def add_memory(
        memories: list[str] = Field(description="要添加的记忆"),
    ) -> bool:
        await pipeline._memory.add("user", memories)
        return True

    @mcp.tool(description="根据查询搜索用户已保存的记忆")
    async def search_memory(
        queries: list[str] = Field(description="要搜索的记忆"),
    ) -> list[SearchResult]:
        return await pipeline._memory.search("user", queries, rerank=True)

    @mcp.tool(description="获取所有已启用的知识库列表，包含文档摘要信息")
    def list_knowledge() -> list[CollectionInfo | CollectionBriefInfo]:
        return pipeline._knowledge.list_collections(True, True)

    @mcp.tool(description="搜索知识库内容，可指定知识库名称或搜索全部已启用的知识库")
    async def search_knowledge(
        queries: list[str] = Field(description="要搜索的相关内容"),
        collection: str | None = Field(
            default=None, description="知识库名，留空则搜索全部知识库"
        ),
        top_k: int = Field(default=5, description="返回条数"),
        rerank: bool = Field(default=True, description="是否重排序"),
    ) -> list[SearchResult]:
        if collection:
            return await pipeline._knowledge.search(
                collection, queries, top_k=top_k, rerank=rerank
            )
        return await pipeline._knowledge.search_all(queries, top_k=top_k, rerank=rerank)

    logger.info("MCP server starting on %s:%d", conf.mcp.host, conf.mcp.port)

    @mcp.custom_route("/health", methods=["GET"])
    async def health(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "service": "rag-mcp"})

    await mcp.run_streamable_http_async()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
