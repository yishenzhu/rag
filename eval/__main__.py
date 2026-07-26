"""`python -m rag.eval` 入口。"""

import argparse
import asyncio

from .datasets import BEIR_DATASETS
from .runner import EvalRunner


def main():
    parser = argparse.ArgumentParser(description="RAG 检索评测 (BEIR)")
    parser.add_argument(
        "--dataset-name",
        required=True,
        choices=BEIR_DATASETS,
        help="BEIR 内置数据集名称 (自动从 HuggingFace 下载)",
    )
    parser.add_argument(
        "--collection", default="eval", help="知识库名称 (默认 eval)"
    )
    parser.add_argument(
        "--threshold", type=float, default=0.0, help="相似度阈值 (默认 0.0)"
    )
    parser.add_argument(
        "--skip-ingest",
        action="store_true",
        help="跳过语料库导入 (已导入时使用)",
    )
    parser.add_argument(
        "--batch-size", type=int, default=2048, help="导入批大小 (默认 2048)"
    )
    args = parser.parse_args()

    runner = EvalRunner(
        dataset_name=args.dataset_name,
        collection=args.collection,
        threshold=args.threshold,
        batch_size=args.batch_size,
    )

    async def _run():
        await runner.setup()
        await runner.run_all(skip_ingest=args.skip_ingest)

    asyncio.run(_run())


if __name__ == "__main__":
    main()
