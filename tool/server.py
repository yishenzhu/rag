import anyio
from mcp.server.fastmcp import FastMCP
from contextlib import asynccontextmanager
from ..core import ServerConfig
from ..rag import Pipeline


@asynccontextmanager
async def run_mcp(conf: ServerConfig, pipeline: Pipeline):

    mcp = FastMCP("RAG MCP", host=conf.host, port=conf.port)

    mcp.tool()(pipeline.add_user_memory)
    mcp.tool()(pipeline.search_user_memory)

    async with anyio.create_task_group() as tg:
        tg.start_soon(mcp.run_streamable_http_async)
        yield
