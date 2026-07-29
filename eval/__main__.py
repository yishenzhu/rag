"""`python -m rag.eval <subcommand>` 入口。

子命令:
    eval     – 检索评测（输出 JSON，--plot 自动绘图）
    plot     – 根据 JSON 报告生成 PNG
"""

import argparse
import asyncio
from pathlib import Path

from .datasets import BEIR_DATASETS
from .runner import EvalRunner
from .plotting import plot


def main():
    parser = argparse.ArgumentParser(description="RAG 检索评测 (BEIR)")
    sub = parser.add_subparsers(dest="command", required=True)

    # ── eval ──
    p_eval = sub.add_parser("eval", help="检索评测（输出 JSON，--plot 自动绘图）")
    p_eval.add_argument("--dataset-name", required=True, choices=BEIR_DATASETS)
    p_eval.add_argument("--collection", default="eval", help="collection 名称（默认 eval）")
    p_eval.add_argument("--threshold", type=float, default=0.0)
    p_eval.add_argument("--plot", action="store_true", help="评测完成后自动生成图表")

    # ── plot ──
    p_plot = sub.add_parser("plot", help="根据 JSON 报告生成 PNG")
    p_plot.add_argument("json_files", nargs="+", help="一个或多个 JSON 报告路径")

    args = parser.parse_args()

    if args.command == "eval":
        async def _run():
            runner = EvalRunner(args.dataset_name, args.collection, args.threshold)
            await runner.setup()
            _, paths = await runner.run_all()

            if args.plot:
                plot(paths)
        asyncio.run(_run())

    elif args.command == "plot":
        paths = [str(Path(p).resolve()) for p in args.json_files]
        plot(paths)


if __name__ == "__main__":
    main()
