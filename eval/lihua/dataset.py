"""LiHua-World 数据集加载。

- ``processed.jsonl``：每行一个会话，metadata 含 source（week3/20260121_1000.txt）、
  datetime（202601211000，会话开始时间）、speakers。
- ``query_set.json``：{qid: {question, answer, evidence, type}}，evidence 形如
  ``20260121_10:00<and>20260701_10:00``，即各证据会话的开始时间。

evidence 与检索结果的对齐键统一取会话 datetime 数值，与知识库 metadata.datetime 一致。
"""

from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass, field
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "dataset"
QUERY_SET = DATA_DIR / "query_set.json"
SESSIONS = DATA_DIR / "processed.jsonl"

# 20260121_10:00 | 20260121_1000 | 20260121
_EV_RE = re.compile(r"^(\d{8})(?:_(\d{2}):(\d{2})|_(\d{4}))?$")
# evidence / answer 里混进的 "Time: "、"Answer: " 之类前缀
_PREFIX_RE = re.compile(r"^(?:Time|Question|Answer)\s*[:：]\s*", re.IGNORECASE)


def parse_dt(evidence: str) -> int | None:
    """单条 evidence → datetime 数值（20260121_10:00 → 202601211000），失败返回 None。"""
    text = _PREFIX_RE.sub("", (evidence or "").strip()).strip()
    m = _EV_RE.match(text)
    if not m:
        return None
    base = int(m.group(1))
    if m.group(2):
        return base * 10000 + int(m.group(2)) * 100 + int(m.group(3))
    if m.group(4):
        return base * 10000 + int(m.group(4))
    return base * 10000


def parse_evidence(evidence: str) -> list[int]:
    """拆分 <and> 连接的 evidence，返回去重后的 datetime 列表（N/A → []）。"""
    if not evidence or evidence.strip().upper() in {"N/A", "NA", "NONE"}:
        return []
    out: list[int] = []
    for part in evidence.split("<and>"):
        dt = parse_dt(part)
        if dt is not None and dt not in out:
            out.append(dt)
    return out


def normalize_answer(answer: str) -> str:
    """归一化答案用于比较：去前缀、去引号、小写、压缩空白。"""
    text = _PREFIX_RE.sub("", (answer or "").strip()).strip('"').strip("。. ")
    return re.sub(r"\s+", " ", text.lower())


@dataclass
class QuerySample:
    """一条评测样本。"""

    qid: str
    question: str
    answer: str  # 归一化后的标准答案
    evidence: str  # 原始 evidence 串
    type: str  # Single / Multi / Null
    gold_dt: list[int] = field(default_factory=list)
    gold_sources: list[str] = field(default_factory=list)


def load_sessions(path: Path = SESSIONS) -> dict[int, str]:
    """会话索引：datetime 数值 → source（week3/20260121_1000.txt）。"""
    index: dict[int, str] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            meta = json.loads(line).get("metadata", {})
            if meta.get("datetime") and meta.get("source"):
                index[int(meta["datetime"])] = meta["source"]
    return index


def load_queries(
    path: Path = QUERY_SET,
    sessions: dict[int, str] | None = None,
    types: list[str] | None = None,
    qids: list[str] | None = None,
    limit: int | None = None,
) -> list[QuerySample]:
    """加载问题集：evidence 解析成 gold_dt，并对齐到知识库中的 gold_sources。"""
    sessions = load_sessions() if sessions is None else sessions
    raw = json.loads(Path(path).read_text(encoding="utf-8"))

    samples: list[QuerySample] = []
    for qid in sorted(raw, key=lambda q: int(q) if q.isdigit() else 1 << 30):
        row = raw[qid]
        if qids and qid not in qids:
            continue
        if types and row.get("type") not in types:
            continue

        gold_dt = parse_evidence(row.get("evidence", ""))
        samples.append(
            QuerySample(
                qid=qid,
                question=(row.get("question") or "").strip(),
                answer=normalize_answer(row.get("answer", "")),
                evidence=(row.get("evidence") or "").strip(),
                type=row.get("type", ""),
                gold_dt=gold_dt,
                gold_sources=[sessions[dt] for dt in gold_dt if dt in sessions],
            )
        )
        if limit and len(samples) >= limit:
            break
    return samples


def stratified_sample(
    samples: list[QuerySample],
    ratio: float = 0.1,
    seed: int = 42,
    min_per_type: int = 1,
) -> list[QuerySample]:
    """按类型比例随机抽样，返回子集（保序）。

    ``ratio`` 是总体的抽样比例；每类型至少保留 ``min_per_type`` 条，
    剩余名额按类型占比分摊。固定 seed 保证同题集两次抽样结果一致。
    """
    if ratio <= 0 or not samples:
        return []
    rng = random.Random(seed)
    by_type: dict[str, list[QuerySample]] = {}
    for s in samples:
        by_type.setdefault(s.type, []).append(s)

    total = len(samples)
    budget = max(1, round(total * ratio))
    budget = min(budget, total)

    # 按占比取整（最大余数法），同时保证每类型至少 min_per_type 条
    n_type = {t: len(v) for t, v in by_type.items()}
    ideal = {t: n * budget / total for t, n in n_type.items()}
    take = {
        t: max(min(n_type[t], min_per_type), int(x))
        for t, x in ideal.items()
    }
    left = budget - sum(take.values())
    if left > 0:
        # 余数最大的类型优先补额
        for t in sorted(ideal, key=lambda t: ideal[t] - int(ideal[t]), reverse=True):
            if left <= 0:
                break
            if take[t] < n_type[t]:
                take[t] += 1
                left -= 1
    if left < 0:
        # 极端小类型触发 min 保底导致超额时，从可减类型中去掉
        for t in sorted(ideal, key=lambda t: ideal[t] - int(ideal[t])):
            if left >= 0:
                break
            if take[t] > min(n_type[t], min_per_type):
                take[t] -= 1
                left += 1

    # 类型内打乱后按额抽取；结果再按原样本顺序排回
    order: dict[str, list[int]] = {}
    for i, s in enumerate(samples):
        order.setdefault(s.type, []).append(i)
    chosen: set[int] = set()
    for t, idxs in order.items():
        rng.shuffle(idxs)
        chosen.update(idxs[: take[t]])
    return [s for i, s in enumerate(samples) if i in chosen]
