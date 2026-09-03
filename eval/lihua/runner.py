"""端到端评测运行器。

对每题：RetrievalAgent 检索 → evidence 指标 + LLM 评分 → 逐条写入 JSONL
（可断点续跑），全部完成后生成聚合报告并打印摘要。
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from ...core import auto_path
from .agent import SEARCH_TOOL, RetrievalAgent, Trajectory, clip
from .dataset import load_queries, stratified_sample
from .judge import aggregate as aggregate_judge
from .judge import judge as judge_sample
from .llm import LLM
from .mcp_client import RagMcpClient
from .metric import K_VALUES
from .metric import aggregate as aggregate_metrics
from .metric import evaluate as evaluate_sample

logger = logging.getLogger(__name__)


@dataclass
class E2EConfig:
    """端到端评测配置。``mode``: ``agent``（LLM 多轮检索）| ``direct``（问题原样单次检索，baseline）。"""

    collection: str = "lihua"
    mcp_url: str = "http://127.0.0.1:9000/mcp"
    mode: str = "agent"
    max_rounds: int = 8
    top_k: int = 5
    doc_chars: int = 1000
    confidence_threshold: float = 0.9  # 置信度自检：证据足以支撑作答的自评置信度达该值即停检索
    judge: bool = True
    judge_doc_chars: int = 500
    concurrency: int = 4
    limit: int | None = None
    qids: list[str] | None = None
    types: list[str] | None = None
    output: str | None = None
    sample_ratio: float | None = None  # 按类型比例随机抽样跑子集（None=全量）
    sample_seed: int = 42
    dataset: str = "lihua"


class E2ERunner:
    def __init__(
        self,
        config: E2EConfig,
        llm: LLM | None = None,
        judge_llm: LLM | None = None,
    ):
        self._cfg = config
        self._llm = llm
        self._judge_llm = judge_llm
        self._sem: asyncio.Semaphore | None = None
        self._lock = asyncio.Lock()
        self._done = 0
        self._name = ""

    async def run(self) -> dict[str, Any]:
        """跑完全部样本，返回报告。"""
        if self._cfg.mode == "agent" and self._llm is None:
            raise RuntimeError("agent 模式需要配置 LLM")
        samples = load_queries(
            types=self._cfg.types,
            qids=self._cfg.qids,
            limit=None if self._cfg.sample_ratio else self._cfg.limit,
        )
        if self._cfg.sample_ratio:
            samples = stratified_sample(
                samples, self._cfg.sample_ratio, seed=self._cfg.sample_seed
            )
            from collections import Counter

            dist = dict(Counter(s.type for s in samples))
            print(
                f"[信息] 按类型抽样 ratio={self._cfg.sample_ratio} seed={self._cfg.sample_seed} "
                f"共 {len(samples)} 题（{dist}）"
            )
        if not samples:
            print("[提示] 没有待评测样本")
            return {}

        self._sem = asyncio.Semaphore(max(1, self._cfg.concurrency))
        self._name = self._cfg.output or self._default_name()
        jsonl_path = auto_path(f"data/{self._name}.jsonl")
        report_path = auto_path(f"data/{self._name}_report.json")

        # 断点续跑：已有输出里的 qid 一律跳过，中断后重跑同命令即可
        done = self._load_done(jsonl_path)
        if done:
            samples = [s for s in samples if s.qid not in done]
            print(f"[信息] 跳过已完成 {len(done)} 题，剩余 {len(samples)} 题")
        if not samples:
            print("[提示] 已全部完成")
            return {}

        print(
            f"[信息] 评测 {len(samples)} 题 | collection={self._cfg.collection} | "
            f"并发={self._cfg.concurrency} | 轨迹: {jsonl_path}"
        )
        await asyncio.gather(*(self._process(sample, jsonl_path) for sample in samples))

        records = self._load_records(jsonl_path)
        report = {
            "dataset": self._cfg.dataset,
            "collection": self._cfg.collection,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "config": asdict(self._cfg),
            "num_samples": len(records),
            "metrics": aggregate_metrics(records),
            "judge": aggregate_judge([r["judge"] for r in records if r.get("judge")]),
            "jsonl_path": jsonl_path,
        }
        await asyncio.to_thread(self._save_report, report, report_path)
        self._print_summary(report)
        return report

    @staticmethod
    def _save_report(report: dict, path: str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

    async def _process(self, sample, jsonl_path: str) -> None:
        """单题：检索 → 指标 → 评分 → 落盘。"""
        async with self._sem:
            try:
                async with RagMcpClient(self._cfg.mcp_url) as client:
                    if self._cfg.mode == "direct":
                        # baseline：问题原样当一条查询，单次检索，不产答案
                        traj = await self._direct_search(client, sample)
                        score = {}
                    else:
                        agent = RetrievalAgent(
                            self._llm, client, self._cfg.collection,
                            max_rounds=self._cfg.max_rounds,
                            top_k=self._cfg.top_k,
                            doc_chars=self._cfg.doc_chars,
                            confidence_threshold=self._cfg.confidence_threshold,
                        )
                        traj = await agent.run(sample)
                        score = (
                            await judge_sample(self._judge_llm, sample, traj, self._cfg.judge_doc_chars)
                            if self._judge_llm
                            else {}
                        )
                # agent 模式不关心排序类指标（hit/recall/mrr/ndcg@k 无意义且与
                # 直连口径不可比），只保留：找全（跨轮覆盖）/ 答案 / 调用代价。
                ks = () if self._cfg.mode == "agent" else K_VALUES
                metrics = evaluate_sample(sample, traj, ks=ks)
            except Exception as e:  # 单题失败不影响整体
                logger.exception("qid=%s 失败", sample.qid)
                traj = Trajectory(qid=sample.qid, error=f"{type(e).__name__}: {e}")
                metrics = evaluate_sample(sample, traj)
                score = {}

            record = {
                "qid": sample.qid,
                "type": sample.type,
                "question": sample.question,
                "gold_answer": sample.answer,
                "evidence": sample.evidence,
                "gold_sources": sample.gold_sources,
                "trajectory": traj.to_dict(),
                "metrics": metrics,
                "judge": score,
            }
            await self._append(jsonl_path, record)

            self._done += 1
            print(
                f"  [{self._done}] qid={sample.qid} {traj.num_queries}查询/"
                f"{len(traj.calls)}调用 召回={metrics.get('cumulative_recall')} "
                f"abstain={metrics.get('abstain')}"
            )

    async def _direct_search(self, client, sample) -> Trajectory:
        """Baseline 直连：question 原样一条查询，单次检索，拼成与 agent 同构的轨迹。"""
        queries = [sample.question]
        record = {"round": 0, "queries": queries, "top_k": self._cfg.top_k,
                  "hits": [], "error": None}
        try:
            results = await client.call(
                SEARCH_TOOL,
                {"queries": queries, "collection": self._cfg.collection,
                 "top_k": self._cfg.top_k},
            )
        except Exception as e:  # noqa: BLE001
            record["error"] = str(e)
            return Trajectory(qid=sample.qid, calls=[record])

        for item in results or []:
            payload = item.get("payload", item)
            meta = payload.get("metadata", {})
            record["hits"].append(
                {
                    "source": meta.get("source", ""),
                    "doc_id": str(meta.get("doc_id") or meta.get("datetime") or ""),
                    "content": clip(payload.get("content", ""), self._cfg.doc_chars),
                }
            )
        return Trajectory(qid=sample.qid, calls=[record])

    async def _append(self, path: str, record: dict) -> None:
        line = json.dumps(record, ensure_ascii=False)
        async with self._lock:
            await asyncio.to_thread(self._write, path, line)

    @staticmethod
    def _write(path: str, line: str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    @staticmethod
    def _load_done(path: str) -> set[str]:
        """已成功完成的 qid（error 记录不算，重跑时补测）。"""
        return {
            r["qid"] for r in E2ERunner._load_records(path)
            if not r.get("trajectory", {}).get("error")
        }

    @staticmethod
    def _load_records(path: str) -> list[dict]:
        """读取全部记录；同一 qid 多条（先失败后成功）取最后一次。"""
        if not Path(path).exists():
            return []
        by_qid: dict[str, dict] = {}
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    record = json.loads(line)
                    by_qid[record["qid"]] = record
        return list(by_qid.values())

    def _default_name(self) -> str:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"{self._cfg.dataset}_{self._cfg.collection}_e2e_{ts}"

    @staticmethod
    def _print_summary(report: dict[str, Any]) -> None:
        overall = report["metrics"]["overall"]
        judge = report["judge"]
        mode = report["config"].get("mode", "agent")

        def fmt(k: str) -> str:
            value = overall.get(k)
            if value is None:
                return "-"
            return f"{value:.4f}" if isinstance(value, float) else str(value)
        print("\n" + "=" * 60)
        print(f"  LiHua-World 评测（{report['num_samples']} 题）mode={mode}")
        print("=" * 60)
        if mode == "direct":
            print(
                f"  排序检索: Hit@5={fmt('hit@5')} Recall@5={fmt('recall@5')} "
                f"NDCG@5={fmt('ndcg@5')} MRR@5={fmt('mrr@5')} "
                f"Precision@5={fmt('precision@5')}"
            )
        print(
            f"  找全: 累积召回(跨轮)={fmt('cumulative_recall')} "
            f"单题召齐全率={fmt('full_recall_rate')} 首轮召回={fmt('first_round_recall')}"
        )
        print(f"  效率: 轮次={fmt('num_rounds')} 查询={fmt('num_queries')} "
              f"冗余调用={fmt('redundant_calls')}")
        if mode == "agent":
            print(
                f"  答案: abstain率={fmt('abstain')} 截断率(超轮次未答)={fmt('truncated')}"
                f"（正确性见下方 LLM 评分 answer_correctness）"
            )
        if judge.get("dimensions"):
            dims = " | ".join(
                f"{n}={d['mean']:.2f}" for n, d in judge["dimensions"].items()
            )
            print(f"  LLM评分(1-5): {dims}（{judge['num_judged']} 题评分）")
        print("=" * 60)
