import argparse
import asyncio
import json
import logging
from beir.datasets.data_loader_hf import HFDataLoader
from beir.retrieval.evaluation import EvaluateRetrieval

from .core import Config, SearchType, Document, auto_path, setup_logger
from .engine import Pipeline

logger = logging.getLogger(__name__)

BEIR_DATASETS = [
    "scifact",
    "nfcorpus",
    "fiqa",
    "trec-covid",
    "arguana",
    "webis-touche2020",
    "cqadupstack",
    "quora",
    "dbpedia-entity",
    "scidocs",
    "fever",
    "climate-fever",
    "nq",
    "msmarco",
    "hotpotqa",
]


def load_dataset(dataset_name: str):
    print(f"[信息] 从 HuggingFace 下载 BEIR 数据集: {dataset_name}")
    loader = HFDataLoader(hf_repo=f"BeIR/{dataset_name}")
    corpus, queries, qrels = loader.load()
    return corpus, queries, qrels


async def run_eval(
    pipeline: Pipeline,
    corpus: dict,
    queries: dict,
    qrels: dict,
    dataset_name: str,
    collection: str = "eval",
    threshold: float = 0.0,
    search_type: SearchType = SearchType.DENSE,
    rerank: bool = False,
    skip_ingest: bool = False,
    batch_size: int = 2048,
):

    k_values = [1, 10, 50, 100]

    if corpus and not skip_ingest:
        print("[信息] 正在导入语料库...")
        documents = [
            Document(
                content=f"{row['title']}\n{row['text']}",
                metadata={"doc_id": row["id"]},
            )
            for row in corpus
        ]
        total = len(documents)
        for i in range(0, total, batch_size):
            batch = documents[i : i + batch_size]
            print(
                f"[信息] 导入批次 {i // batch_size + 1}/{(total + batch_size - 1) // batch_size} ({len(batch)} 文档)"
            )
            await pipeline._knowledge.ingest(collection, batch, chunk=False)
        print("[信息] 导入完成")

    metrics: dict[str, float] = {}
    for k in k_values:
        results: dict[str, dict[str, float]] = {}
        for row in queries:
            qid, query = row["id"], row["text"]
            search_results = await pipeline._knowledge.search(
                collection, query, k, threshold, search_type, rerank
            )
            results[qid] = {
                r.payload["metadata"]["doc_id"]: r.score for r in search_results
            }
        ndcg, _map, recall, precision = EvaluateRetrieval.evaluate(qrels, results, [k])
        mrr = EvaluateRetrieval.evaluate_custom(qrels, results, [k], metric="mrr")
        metrics.update({**ndcg, **_map, **recall, **precision, **mrr})

    report = {
        "dataset": dataset_name,
        "collection": collection,
        "search_type": search_type.value,
        "rerank": rerank,
        "num_queries": len(queries),
        "num_corpus": len(corpus),
        "metrics": metrics,
    }

    print(json.dumps(report, ensure_ascii=False, indent=2))
    from pathlib import Path

    from datetime import datetime

    name = dataset_name
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = auto_path(
        f"data/{name}_{search_type.value}_{'rerank' if rerank else 'no_rerank'}_{ts}.json"
    )

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"[信息] 报告已保存: {out_path}")

    return report


async def run_all(
    dataset_name: str,
    collection: str = "eval",
    threshold: float = 0.0,
    skip_ingest: bool = False,
    batch_size: int = 2048,
):
    corpus, queries, qrels = load_dataset(dataset_name)
    print(
        f"[信息] 语料库: {len(corpus)} 文档, 查询: {len(queries)} 条, 标注: {len(qrels)} 条"
    )

    conf = Config.load()
    setup_logger(conf.log)
    pipeline = await Pipeline(conf.rag).setup()

    combinations = [
        (SearchType.DENSE, False),
        (SearchType.DENSE, True),
        (SearchType.HYBRID, False),
        (SearchType.HYBRID, True),
    ]

    for i, (search_type, rerank) in enumerate(combinations):
        print(
            f"\n{'=' * 60}\n[信息] 运行组合 {i + 1}/4: search_type={search_type.value}, rerank={rerank}\n{'=' * 60}"
        )
        await run_eval(
            pipeline=pipeline,
            corpus=corpus,
            queries=queries,
            qrels=qrels,
            dataset_name=dataset_name,
            collection=collection,
            threshold=threshold,
            search_type=search_type,
            rerank=rerank,
            skip_ingest=skip_ingest or i > 0,
            batch_size=batch_size,
        )


def main():
    parser = argparse.ArgumentParser(description="RAG 检索评测 (BEIR)")
    parser.add_argument(
        "--dataset-name",
        required=True,
        choices=BEIR_DATASETS,
        help="BEIR 内置数据集名称 (自动从 HuggingFace 下载)",
    )
    parser.add_argument("--collection", default="eval", help="知识库名称 (默认 eval)")
    parser.add_argument(
        "--threshold", type=float, default=0.0, help="相似度阈值 (默认 0.0)"
    )
    parser.add_argument(
        "--skip-ingest", action="store_true", help="跳过语料库导入 (已导入时使用)"
    )
    parser.add_argument(
        "--batch-size", type=int, default=2048, help="导入批大小 (默认 2048)"
    )
    args = parser.parse_args()

    asyncio.run(
        run_all(
            dataset_name=args.dataset_name,
            collection=args.collection,
            threshold=args.threshold,
            skip_ingest=args.skip_ingest,
            batch_size=args.batch_size,
        )
    )


if __name__ == "__main__":
    main()
