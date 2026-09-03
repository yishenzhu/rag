"""evidence 对齐的规则化指标。

把 query_set 的 gold evidence（会话 datetime）当作正解，与检索轨迹逐轮对齐：
- 累积（跨轮去重、按轮序拼接）Hit@k / Recall@k / Precision@k / MRR@k；
- 逐轮召回、召齐全所需轮次；
- 调用代价：轮次数 / 查询数 / 返回文档数 / 冗余调用数；
- 答案：abstain（模型是否回答 "Insufficient information"，Null 类应如此作答）。
"""

from __future__ import annotations

import math
from typing import Any

from .agent import Trajectory
from .dataset import QuerySample, normalize_answer

K_VALUES = (1, 3, 5, 10)


def evaluate(sample: QuerySample, traj: Trajectory, ks: tuple[int, ...] = K_VALUES) -> dict[str, Any]:
    """单题指标：检索（evidence 命中）+ 调用代价 + 答案。"""
    gold = {str(dt) for dt in sample.gold_dt}
    metrics: dict[str, Any] = {
        "num_calls": len(traj.calls),
        "num_rounds": len({c["round"] for c in traj.calls}),
        "num_queries": traj.num_queries,
        "has_error": bool(traj.error),
        "truncated": int(bool(getattr(traj, "truncated", False))),  # 超轮次未产出答案
        "evidence_count": len(gold),
    }

    # 跨轮去重累积列表，同时算逐轮/累积召回与冗余调用
    ordered: list[str] = []
    seen: set[str] = set()
    cum_gold: set[str] = set()
    round_recalls: list[float] = []
    cumulative: list[float] = []
    redundant = 0
    for call in traj.calls:
        keys = [
            (h.get("doc_id") or h.get("source") or "").strip()
            for h in call["hits"]
            if (h.get("doc_id") or h.get("source") or "").strip()
        ]
        if keys and all(k in seen for k in keys):
            redundant += 1
        hit_gold = {k for k in keys if k in gold}
        cum_gold |= hit_gold
        for k in keys:
            if k not in seen:
                seen.add(k)
                ordered.append(k)
        if gold:
            round_recalls.append(len(hit_gold) / len(gold))
            cumulative.append(len(cum_gold) / len(gold))
    metrics["docs_total"] = sum(len(c["hits"]) for c in traj.calls)
    metrics["docs_unique"] = len(seen)
    metrics["redundant_calls"] = redundant

    if gold:
        first_rank = next((i for i, k in enumerate(ordered, 1) if k in gold), None)
        for k in ks:
            top = ordered[:k]
            n = len([x for x in top if x in gold])
            metrics[f"hit@{k}"] = float(bool(n))
            metrics[f"recall@{k}"] = round(n / len(gold), 4)
            metrics[f"precision@{k}"] = round(n / len(top), 4) if top else 0.0
            metrics[f"mrr@{k}"] = round(1 / first_rank, 4) if first_rank and first_rank <= k else 0.0
            idcg = sum(1.0 / math.log2(i + 2) for i in range(min(len(gold), k)))
            dcg = sum(
                1.0 / math.log2(i + 2)
                for i, doc in enumerate(ordered[:k])
                if doc in gold
            )
            metrics[f"ndcg@{k}"] = round(dcg / idcg, 4) if idcg else 0.0
        metrics["cumulative_recall"] = round(cumulative[-1], 4) if cumulative else 0.0
        metrics["round_recalls"] = [round(r, 4) for r in round_recalls]
        metrics["first_round_recall"] = round(round_recalls[0], 4) if round_recalls else 0.0
        full_round = next((i for i, r in enumerate(cumulative, 1) if r >= 1.0 - 1e-9), None)
        metrics["rounds_to_full_recall"] = full_round
    else:
        # Null 类无 gold：命中类指标无定义
        for k in ks:
            for name in ("hit", "recall", "precision", "mrr", "ndcg"):
                metrics[f"{name}@{k}"] = None
        metrics["cumulative_recall"] = None
        metrics["round_recalls"] = []
        metrics["first_round_recall"] = None
        metrics["rounds_to_full_recall"] = None

    # 答案（不做字符串匹配：开放生成答案措辞多样，EM/F1 无意义且中文分词不严谨。
    # 是否"答对"交给 judge 的 answer_correctness 语义判断；这里只记 abstain。）
    pred = normalize_answer(traj.final_answer)
    metrics["abstain"] = float(pred == normalize_answer("Insufficient information"))
    return metrics


def aggregate(records: list[dict[str, Any]]) -> dict[str, Any]:
    """聚合整体与按 type 分组的指标均值。records 每项含 type 与 metrics。"""
    def summarize(items: list[dict[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {"num_samples": len(items)}
        if not items:
            return out
        keys = sorted({k for m in items for k, v in m.items() if isinstance(v, (int, float))})
        for key in keys:
            values = [m[key] for m in items if m.get(key) is not None]
            out[key] = round(sum(values) / len(values), 4) if values else None
        full = [m["rounds_to_full_recall"] for m in items
                if m.get("rounds_to_full_recall") is not None]
        out["full_recall_rate"] = round(len(full) / len(items), 4)
        out["avg_rounds_to_full_recall"] = round(sum(full) / len(full), 4) if full else None
        return out

    by_type: dict[str, Any] = {}
    for qtype in sorted({r.get("type", "") for r in records}):
        group = [r["metrics"] for r in records if r.get("type") == qtype]
        by_type[qtype or "unknown"] = summarize(group)
    return {
        "num_samples": len(records),
        "overall": summarize([r["metrics"] for r in records]),
        "by_type": by_type,
    }
