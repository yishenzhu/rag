"""检索智能体：LLM 生成查询 → 多次调用 RAG MCP 工具 → 产出答案。

轨迹记录在 :class:`Trajectory`：每次调用的查询、返回的会话（含 source）、最终答案，
供 evidence 对齐与 LLM 评分使用。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from .dataset import QuerySample
from .llm import LLM, parse_json
from .mcp_client import RagMcpClient

SEARCH_TOOL = "search_knowledge"


class FinalAnswer(BaseModel):
    """最终答案结构（json_object 模式下用于解析校验）。"""

    answer: str = Field(description="是/否问题只回答 Yes 或 No；无依据回答 Insufficient information")
    confidence: float | None = Field(
        default=None, ge=0.0, le=1.0,
        description="对答案的自检置信度（0~1）：证据足以支撑该答案的把握",
    )
    evidence_sources: list[str] = Field(description="依据会话 source，形如 week45/20261109_0900.txt")
    reason: str = Field(description="一句话依据")


SYSTEM_PROMPT = """你是一个检索智能体，需在聊天记录知识库 {collection} 中检索证据来回答问题。

流程：
1. 先检索问题涉及的各事件/实体。每轮收到检索结果后先做一次置信度自检：把问题拆成
   各要素（事件、实体、时间先后等），核对已检索内容是否把它们逐项直接覆盖。
2. 置信度不足（仍缺某要素的直接证据）时，只针对缺口发起新一轮检索（每次 1~2 条精准
   查询），不要重复已查过的信息，也不要检索与缺口无关的内容。
3. 只能基于检索到的内容作答，禁止编造；确实找不到依据就回答 "Insufficient information"。

最终答案只输出一个 JSON 对象（不要多余文字），形如：
   {{"answer": "...", "confidence": 0.9, "evidence_sources": ["week45/20261109_0900.txt"], "reason": "一句话依据"}}
   answer：是/否问题只回答 Yes 或 No；开放问题用简短短语；无依据时 Insufficient information。
   confidence：对"已有证据足以支撑该答案"的自检置信度（0~1）；只有 >= {confidence_threshold} 才应停检索作答。
   evidence_sources：实际支撑结论的检索会话 source，无依据时为空数组。
   reason：一句话依据。
"""


def clip(text: str, limit: int) -> str:
    text = text or ""
    return text if limit <= 0 or len(text) <= limit else text[:limit] + " …[截断]"


@dataclass
class Trajectory:
    """一个问题的检索轨迹。``calls`` 每项：

    {round, queries, top_k, hits: [{source, doc_id, content}], error}
    """

    qid: str
    calls: list[dict] = field(default_factory=list)
    final_answer: str = ""
    final_json: dict | None = None
    error: str | None = None
    truncated: bool = False  # True=跑满 max_rounds 仍在调工具/空响应，未产出最终答案

    @property
    def num_queries(self) -> int:
        return sum(len(c["queries"]) for c in self.calls)

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "num_calls": len(self.calls), "num_queries": self.num_queries}


class RetrievalAgent:
    """单问题的多轮检索智能体（function calling 模式）。"""

    def __init__(
        self,
        llm: LLM,
        client: RagMcpClient,
        collection: str,
        max_rounds: int = 8,
        top_k: int = 5,
        doc_chars: int = 1000,
        confidence_threshold: float = 0.9,
    ):
        self._llm = llm
        self._client = client
        self._collection = collection
        self._max_rounds = max_rounds
        self._top_k = top_k
        self._doc_chars = doc_chars
        self._confidence_threshold = confidence_threshold

    async def run(self, sample: QuerySample) -> Trajectory:
        traj = Trajectory(qid=sample.qid)
        tools = [
            t for t in await self._client.list_tools()
            if t["function"]["name"] == SEARCH_TOOL
        ]
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": SYSTEM_PROMPT.format(
                    collection=self._collection,
                    confidence_threshold=self._confidence_threshold,
                ),
            },
            {"role": "user", "content": f"问题：{sample.question}"},
        ]

        final = ""
        for round_index in range(self._max_rounds):
            msg = await self._llm.chat(messages, tools=tools)
            if not msg.tool_calls:
                # 模型主动停止：该轮 content 即最终答案（SYSTEM_PROMPT 要求只输出 JSON）
                final = msg.content or ""
                break
            messages.append(
                {
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [
                        {
                            "id": c.id,
                            "type": "function",
                            "function": {"name": c.function.name, "arguments": c.function.arguments},
                        }
                        for c in msg.tool_calls
                    ],
                }
            )
            for call in msg.tool_calls:
                if call.function.name != SEARCH_TOOL:
                    content = json.dumps(
                        {"error": f"不支持的工具: {call.function.name}"}, ensure_ascii=False
                    )
                else:
                    content = await self.search(call.function.arguments, round_index, traj)
                messages.append(
                    {"role": "tool", "tool_call_id": call.id, "content": content}
                )

        if not final.strip():
            # 跑满 max_rounds 仍在调工具、或模型停止但给出空回复：不做兜底强制收敛，
            # 视为超轮次未产出答案（截断），该题按答案错误处理（judge 侧 answer_correctness=1）。
            traj.truncated = True
            return traj
        try:
            data = FinalAnswer.model_validate(parse_json(final))
            traj.final_json = data.model_dump()
            traj.final_answer = data.answer
        except ValueError:
            traj.final_json = None
            traj.final_answer = final.strip()
        return traj

    async def search(self, arguments: str, round_index: int, traj: Trajectory) -> str:
        """处理一次 search_knowledge 调用：记录查询与命中（含 source），返回给模型看的文本。"""
        queries = json.loads(arguments or "{}").get("queries", [])
        record = {"round": round_index, "queries": queries, "top_k": self._top_k,
                  "hits": [], "error": None}
        traj.calls.append(record)

        try:
            results = await self._client.call(
                SEARCH_TOOL,
                {"queries": queries, "collection": self._collection, "top_k": self._top_k},
            )
        except Exception as e:  # noqa: BLE001 - 参数/服务错误回给模型，让其自行修正
            record["error"] = str(e)
            return json.dumps({"error": f"检索失败: {e}"}, ensure_ascii=False)

        for item in results or []:
            payload = item.get("payload", item)
            meta = payload.get("metadata", {})
            record["hits"].append(
                {
                    "source": meta.get("source", ""),
                    "doc_id": str(meta.get("doc_id") or meta.get("datetime") or ""),
                    "content": clip(payload.get("content", ""), self._doc_chars),
                }
            )

        if not record["hits"]:
            return f"查询 {queries} 未返回任何结果，请换用其他查询。"
        text = f"查询 {queries} 返回 {len(record['hits'])} 条："
        for index, hit in enumerate(record["hits"], start=1):
            text += f"\n[{index}] source: {hit['source']}\n{hit['content']}"
        return text
