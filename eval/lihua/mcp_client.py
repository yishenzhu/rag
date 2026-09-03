"""RAG MCP 客户端（最小实现）。

工具由 ``mcp_svr.py`` 提供，这里只负责连上并调用：
``search_knowledge`` 返回原始结果（每项形如 {"payload": {"content", "metadata"}}，
metadata 含 source / datetime / doc_id），不额外封装。

用法::

    async with RagMcpClient() as client:
        hits = await client.call(
            "search_knowledge",
            {"queries": ["query"], "collection": "lihua", "top_k": 5},
        )
        hits[0]["payload"]["metadata"]["source"]
"""

from __future__ import annotations

import json
from contextlib import AsyncExitStack
from datetime import timedelta
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

DEFAULT_URL = "http://127.0.0.1:9000/mcp"


class RagMcpClient:
    """MCP 客户端。每个并发任务一个实例（一个 session）。"""

    def __init__(self, url: str = DEFAULT_URL, timeout: float = 120.0):
        self._url = url
        self._timeout = timeout
        self._stack = AsyncExitStack()
        self._session: ClientSession | None = None

    async def __aenter__(self):
        read, write, _ = await self._stack.enter_async_context(
            streamablehttp_client(
                url=self._url,
                timeout=timedelta(seconds=self._timeout),
                sse_read_timeout=timedelta(seconds=self._timeout),
            )
        )
        self._session = await self._stack.enter_async_context(ClientSession(read, write))
        await self._session.initialize()
        return self

    async def __aexit__(self, *exc_info) -> bool:
        await self._stack.aclose()
        self._session = None
        return False

    async def list_tools(self) -> list[dict]:
        """列出 MCP 工具（OpenAI tools 兼容格式）。"""
        res = await self._session.list_tools()
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description or "",
                    "parameters": t.inputSchema or {"type": "object", "properties": {}},
                },
            }
            for t in res.tools
        ]

    async def call(self, name: str, arguments: dict[str, Any]) -> Any:
        """调用工具，返回解析后的 Python 对象（失败抛 RuntimeError）。"""
        if self._session is None:
            raise RuntimeError("RagMcpClient 未连接，请在 async with 中使用")

        res = await self._session.call_tool(name, arguments)
        text = "".join(getattr(c, "text", "") or "" for c in res.content)
        if res.isError:
            raise RuntimeError(f"MCP {name} 调用失败: {text}")

        data = res.structuredContent
        if isinstance(data, dict) and "result" in data:
            # FastMCP 对非 dict 返回值包装成 {"result": ...}
            return data["result"]
        if data is not None:
            return data
        return json.loads(text) if text else []
