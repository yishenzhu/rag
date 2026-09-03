"""`python -m rag.eval.lihua` 入口：LiHua-World 端到端评测。

大模型配置：环境变量 OPENAI_MODEL / OPENAI_API_KEY / OPENAI_BASE_URL
（或项目根 .env），也可用 --model / --api-key / --base-url 覆盖。

示例::

    PYTHONPATH=.. python -m rag.eval.lihua -c lihua --limit 20
    PYTHONPATH=.. python -m rag.eval.lihua -c lihua --types Multi --output lihua_multi --resume
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from .llm import LLM, LLMConfig
from .runner import E2EConfig, E2ERunner


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="LiHua-World 端到端评测：LLM 生成查询→调用 RAG MCP→evidence 对齐 + LLM 评分",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("-c", "--collection", default="lihua", help="知识库名")
    parser.add_argument("--mcp-url", default="http://127.0.0.1:9000/mcp", help="MCP 服务地址")

    run = parser.add_argument_group("评测运行")
    run.add_argument(
        "--mode", default="agent", choices=("agent", "direct"),
        help="agent=LLM 多轮检索+评分；direct=问题原样单次检索（baseline，无答案/评分）",
    )
    run.add_argument("--limit", type=int, default=None, help="只评测前 N 题")
    run.add_argument("--qids", default=None, help="只评测指定 qid，逗号分隔")
    run.add_argument("--types", default=None, help="只评测指定类型，逗号分隔（Single/Multi/Null）")
    run.add_argument(
        "--sample-ratio", type=float, default=None,
        help="按类型比例随机抽一部分跑（如 0.1≈64 题）；与 --limit 二选一",
    )
    run.add_argument("--sample-seed", type=int, default=42, help="抽样随机种子（保证可复现）")
    run.add_argument("--concurrency", type=int, default=8, help="并发题数")
    run.add_argument("--output", default=None, help="输出文件名前缀（默认带时间戳；中断后用同名重跑即续跑）")

    agent = parser.add_argument_group("检索智能体")
    agent.add_argument("--max-rounds", type=int, default=8, help="每题最多检索轮次（跑满仍未给出答案算截断/答错，不再兜底）")
    agent.add_argument(
        "--confidence-threshold", type=float, default=0.9,
        help="置信度自检阈值：模型自评置信度达该值即停止检索直接作答",
    )
    agent.add_argument("--top-k", type=int, default=5, help="每次检索返回条数")
    agent.add_argument("--doc-chars", type=int, default=1000, help="记录/回灌正文的截断长度")
    agent.add_argument("--no-judge", action="store_true", help="不做 LLM 多角度评分")
    agent.add_argument("--judge-doc-chars", type=int, default=500, help="评分时正文截断长度")

    llm = parser.add_argument_group("LLM（OpenAI 兼容）")
    llm.add_argument("--model", default=None, help="模型名")
    llm.add_argument("--api-key", default=None, help="API Key")
    llm.add_argument("--base-url", default=None, help="API 地址")
    llm.add_argument("--judge-model", default=None, help="评分模型（默认同 agent）")
    llm.add_argument("--temperature", type=float, default=None, help="采样温度")
    llm.add_argument("--max-tokens", type=int, default=None)
    llm.add_argument("--timeout", type=float, default=None, help="请求超时秒数")
    llm.add_argument("--max-retries", type=int, default=None)
    parser.add_argument("--log-level", default="INFO")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s|%(levelname)-5s|%(message)s",
    )
    cfg = E2EConfig(
        collection=args.collection,
        mcp_url=args.mcp_url,
        mode=args.mode,
        max_rounds=args.max_rounds,
        top_k=args.top_k,
        doc_chars=args.doc_chars,
        confidence_threshold=args.confidence_threshold,
        judge=not args.no_judge,
        judge_doc_chars=args.judge_doc_chars,
        concurrency=args.concurrency,
        limit=args.limit,
        qids=[q.strip() for q in args.qids.split(",")] if args.qids else None,
        types=[t.strip() for t in args.types.split(",")] if args.types else None,
        output=args.output,
        sample_ratio=args.sample_ratio,
        sample_seed=args.sample_seed,
    )

    overrides = {
        "model": args.model, "api_key": args.api_key, "base_url": args.base_url,
        "temperature": args.temperature, "max_tokens": args.max_tokens,
        "timeout": args.timeout, "max_retries": args.max_retries,
    }

    async def _run() -> None:
        agent_llm: LLM | None = None
        judge_llm: LLM | None = None
        try:
            if cfg.mode == "agent":
                try:
                    agent_cfg = LLMConfig.from_env(**overrides)
                    judge_cfg = (
                        LLMConfig.from_env(model=args.judge_model, **{k: v for k, v in overrides.items() if k != "model"})
                        if args.judge_model else agent_cfg
                    )
                except ValueError as e:
                    print(f"[错误] {e}", file=sys.stderr)
                    return
                agent_llm = LLM(agent_cfg)
                judge_llm = LLM(judge_cfg) if cfg.judge else None
            await E2ERunner(cfg, agent_llm, judge_llm).run()
        finally:
            if agent_llm is not None:
                await agent_llm.aclose()
            if judge_llm is not None and judge_llm is not agent_llm:
                await judge_llm.aclose()

    asyncio.run(_run())


if __name__ == "__main__":
    main()
