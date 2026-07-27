"""`python -m rag.eval <subcommand>` 入口。

子命令:
    ingest   – 将数据集导入 collection
    eval     – 检索评测（输出 JSON，--plot 自动绘图）
    plot     – 根据 JSON 报告生成 PNG
"""

import argparse
import asyncio
from pathlib import Path

from .datasets import BEIR_DATASETS
from .runner import EvalRunner
from .ingest import IngestRunner
from .plotting import plot, plot_comparison


def _add_common_args(p: argparse.ArgumentParser):
    p.add_argument("--dataset-name", required=True, choices=BEIR_DATASETS)


def _add_chunk_args(p: argparse.ArgumentParser):
    p.add_argument("--chunker-type", default="none",
                   choices=["none", "recursive", "semantic"])
    p.add_argument("--chunk-size", type=int, default=512)
    p.add_argument("--chunk-overlap", type=int, default=64)


def main():
    parser = argparse.ArgumentParser(description="RAG 检索评测 (BEIR)")
    sub = parser.add_subparsers(dest="command", required=True)

    # ── ingest ──
    p_ingest = sub.add_parser("ingest", help="将数据集导入 collection")
    _add_common_args(p_ingest)
    p_ingest.add_argument("--collection", default="eval")
    p_ingest.add_argument("--batch-size", type=int, default=512)
    _add_chunk_args(p_ingest)

    # ── eval ──
    p_eval = sub.add_parser("eval", help="检索评测（输出 JSON，--plot 自动绘图）")
    _add_common_args(p_eval)
    p_eval.add_argument(
        "--collections", nargs="+", default=["eval"],
        help="一个或多个 collection 名称（默认 eval），多个时自动跨对比"
    )
    p_eval.add_argument("--threshold", type=float, default=0.0)
    p_eval.add_argument("--plot", action="store_true", help="评测完成后自动生成图表")

    # ── plot ──
    p_plot = sub.add_parser("plot", help="根据 JSON 报告生成 PNG")
    p_plot.add_argument("json_files", nargs="+", help="一个或多个 JSON 报告路径")

    args = parser.parse_args()

    if args.command == "eval":
        async def _run():
            runner = EvalRunner(args.dataset_name, args.collections, args.threshold)
            await runner.setup()
            _, paths_by_col = await runner.run_all()

            if args.plot:
                for col_paths in paths_by_col.values():
                    for p in col_paths:
                        plot(p)
                    if len(col_paths) > 1:
                        plot_comparison(col_paths)
                if len(paths_by_col) > 1:
                    all_paths = [p for paths in paths_by_col.values() for p in paths]
                    plot_comparison(all_paths)
        asyncio.run(_run())

    elif args.command == "ingest":
        async def _run():
            ingester = IngestRunner(
                args.dataset_name, args.collection,
                chunker_type=args.chunker_type,
                chunk_size=args.chunk_size,
                chunk_overlap=args.chunk_overlap,
                batch_size=args.batch_size,
            )
            await ingester.setup()
            await ingester.run()
        asyncio.run(_run())

    elif args.command == "plot":
        paths = [str(Path(p).resolve()) for p in args.json_files]
        if len(paths) == 1:
            plot(paths[0])
        else:
            plot_comparison(paths)


if __name__ == "__main__":
    main()
