"""LLM 裁判：对一次检索轨迹做多角度评分（各 1~5 分）。

裁判拿到问题、标准答案、gold evidence 与完整检索轨迹（每次查询 + 返回的 source），
按 5 个维度给分并附理由。输出由 :class:`JudgeResult`（BaseModel）结构化约束。
"""

from __future__ import annotations

import asyncio
from typing import Any

from pydantic import BaseModel, Field

from .agent import Trajectory, clip
from .dataset import QuerySample
from .llm import LLM, parse_json

# (维度, 打分要点)，供提示词与聚合共用
DIMENSIONS: list[tuple[str, str]] = [
    ("query_quality", "查询质量：查询是否贴合问题、覆盖各事件/实体，是否空泛或跑偏"),
    ("retrieval_efficiency", "检索效率：是否用尽量少的轮次/查询命中证据，有无重复低效调用"),
    ("evidence_recall", "证据召回：返回的 source 是否命中 gold evidence 对应的会话"),
    ("answer_correctness", "答案正确性：最终答案与标准答案语义是否一致"),
    ("groundedness", "依据充分性：答案能否由检索内容直接支撑，有无臆测"),
]

SYSTEM_PROMPT = """你是 RAG 系统评测裁判。你会拿到用户问题、标准答案、gold evidence（应被检索到的会话）、
智能体的逐次检索记录（每次的查询与返回的会话片段）与最终答案。

请按 5 个维度打分并各给一句话理由：
{criteria}
评分锚点：5=很好，4=较好有小瑕疵，3=一般，2=较差，1=很差。
若标准答案为 Insufficient information，正确地判断无依据并如此回答应得高分。
只输出一个 JSON 对象（每个维度形如 {{"score": 1~5, "reason": "..."}}, 另含 comment 字段），不要多余文字。"""


class JudgeScore(BaseModel):
    """单个维度的评分。"""

    score: int = Field(description="1~5 分，5 最好", ge=1, le=5)
    reason: str = Field(description="一句话理由")


class JudgeResult(BaseModel):
    """裁判结果。维度名与 DIMENSIONS 一一对应。"""

    query_quality: JudgeScore
    retrieval_efficiency: JudgeScore
    evidence_recall: JudgeScore
    answer_correctness: JudgeScore
    groundedness: JudgeScore
    comment: str = Field(description="一句话总体评价")


def _criteria() -> str:
    return "\n".join(f"- {name}：{desc}" for name, desc in DIMENSIONS)


def build_messages(sample: QuerySample, traj: Trajectory, doc_chars: int = 500) -> list[dict]:
    """构造裁判输入：问题 + 标准答案 + gold evidence + 检索轨迹 + 最终答案。"""
    lines = [
        f"【问题】{sample.question}",
        f"【标准答案】{sample.answer}",
        f"【gold evidence】{sample.evidence or 'N/A'}",
        f"【gold evidence 对应会话】{', '.join(sample.gold_sources) or 'N/A'}",
        "",
        f"【检索轨迹】共 {len(traj.calls)} 次调用 / {traj.num_queries} 条查询",
    ]
    for call in traj.calls:
        status = f"失败：{call['error']}" if call.get("error") else f"返回 {len(call['hits'])} 条"
        lines.append(f"\n- 第 {call['round'] + 1} 轮调用 {status}，查询：{call['queries']}")
        for hit in call["hits"]:
            lines.append(f"  · source: {hit['source']}")
            lines.append(f"    {clip(hit['content'], doc_chars)}")
    lines += [
        "",
        f"【最终答案】{traj.final_answer or '（空）'}",
        f"【模型给出的依据会话】{traj.final_json.get('evidence_sources', []) if traj.final_json else '（无）'}",
    ]
    if not (traj.final_answer or "").strip():
        lines.append("\n注意：最终答案为空——智能体在限定轮次内未产出答案（截断/超轮次），"
                     "该题答案视为错误。")
    return [
        {"role": "system", "content": SYSTEM_PROMPT.format(criteria=_criteria())},
        {"role": "user", "content": "\n".join(lines)},
    ]


async def judge(llm: LLM, sample: QuerySample, traj: Trajectory, doc_chars: int = 500) -> dict:
    """单题评分，返回 JudgeResult 的 dict；失败返回 {"error": ..., "raw": ...} 不中断评测。

    - 最终答案为空（截断/超轮次未产出答案）：确定性判 answer_correctness=1（答案错误），
      其余维度仍交 LLM 裁判评估；
    - json_object 偶发空响应（服务端间歇问题），最多重试 3 次。
    """
    last: dict = {"error": "未评分"}
    for attempt in range(3):
        last = await _judge_once(llm, sample, traj, doc_chars)
        if "error" not in last:
            if not (traj.final_answer or "").strip():
                last["answer_correctness"] = {
                    "score": 1,
                    "reason": "最终答案为空（限定轮次内未产出答案），按答案错误计",
                }
            return last
        await asyncio.sleep(1 + attempt * 2)
    return last


async def _judge_once(llm: LLM, sample: QuerySample, traj: Trajectory, doc_chars: int) -> dict:
    try:
        msg = await llm.chat(build_messages(sample, traj, doc_chars), json_mode=True)
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}
    try:
        data = JudgeResult.model_validate(parse_json(msg.content))
        return data.model_dump()
    except Exception as e:  # noqa: BLE001 - 保存原始输出便于诊断
        return {"error": f"解析失败: {e}", "raw": (msg.content or "")[:500]}


def aggregate(results: list[dict]) -> dict[str, Any]:
    """聚合评分：各维度均值 / 分布，以及失败数。"""
    judged = [r for r in results if r.get("query_quality")]
    dims: dict[str, Any] = {}
    for name, _ in DIMENSIONS:
        scores = [r[name]["score"] for r in judged if name in r]
        if not scores:
            continue
        dims[name] = {
            "mean": round(sum(scores) / len(scores), 4),
            "n": len(scores),
            "dist": {str(s): scores.count(s) for s in sorted(set(scores))},
        }
    means = [d["mean"] for d in dims.values()]
    return {
        "num_judged": len(judged),
        "num_failed": len(results) - len(judged),
        "dimensions": dims,
        "overall_mean": round(sum(means) / len(means), 4) if means else None,
    }
