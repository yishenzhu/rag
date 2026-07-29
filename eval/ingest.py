"""加载文档或 BEIR 数据集，导入到 RAG 知识库。

两种数据源（二选一）：
  本地文档：python -m rag.eval.ingest <source> -c <collection>
  BEIR 数据集：python -m rag.eval.ingest --dataset-name scifact -c eval [--chunker-type none]

通过 HTTP 调用运行中的 RAG 服务（/knowledge）完成建表与导入。
文档级评测建议用 --chunker-type none（每篇文档一个向量）。
"""

import argparse
import sys

import httpx

from ..engine import DocumentLoader
from ..core import Document
from .datasets import load_corpus


def main():
    parser = argparse.ArgumentParser(description="导入文档/BEIR 数据集到 RAG 知识库")
    parser.add_argument("source", nargs="?", help="文档文件或目录路径（与 --dataset-name 二选一）")
    parser.add_argument("--dataset-name", help="BEIR 数据集名称（如 scifact），与 source 二选一")
    parser.add_argument("-c", "--collection", required=True, help="目标知识库名称")
    parser.add_argument("--host", default="http://localhost:8001", help="RAG 服务地址")
    parser.add_argument("--chunk-size", type=int, default=None, help="分块大小（默认由服务端决定）")
    parser.add_argument("--chunk-overlap", type=int, default=None, help="分块重叠大小（默认由服务端决定）")
    parser.add_argument("--chunker-type", choices=["recursive", "semantic", "none"], default=None,
                        help="切分策略（默认由服务端决定；BEIR 文档级评测建议 none）")
    parser.add_argument("--batch-size", type=int, default=512, help="每批次导入文档数（默认 512）")

    args = parser.parse_args()

    if bool(args.source) == bool(args.dataset_name):
        parser.error("必须且只能指定 source 或 --dataset-name 之一")

    # 加载文档
    if args.dataset_name:
        documents = _load_dataset_corpus(args.dataset_name)
    else:
        try:
            documents = DocumentLoader().load(args.source)
        except (FileNotFoundError, ValueError) as e:
            print(f"[错误] {e}", file=sys.stderr)
            sys.exit(1)

    if not documents:
        print("[提示] 未找到任何可导入的文档")
        sys.exit(0)

    print(f"[信息] 共加载 {len(documents)} 个文档，正在分批发送至 RAG 服务...")

    _ensure_collection(args.host, args.collection)

    # 批量导入
    url = f"{args.host.rstrip('/')}/knowledge/ingest"
    total = 0
    with httpx.Client(timeout=300) as client:
        for i in range(0, len(documents), args.batch_size):
            batch = documents[i : i + args.batch_size]
            payload = {"collection": args.collection, "documents": [d.model_dump() for d in batch]}
            if args.chunk_size is not None:
                payload["chunk_size"] = args.chunk_size
            if args.chunk_overlap is not None:
                payload["chunk_overlap"] = args.chunk_overlap
            if args.chunker_type is not None:
                payload["chunker_type"] = args.chunker_type

            try:
                rsp = client.post(url, json=payload)
                rsp.raise_for_status()
                result = rsp.json()
            except httpx.HTTPError as e:
                print(f"[错误] 请求 RAG 服务失败: {e}", file=sys.stderr)
                sys.exit(1)

            if result.get("success"):
                total += result.get("count", len(batch))
                print(f"[信息] 已导入 {min(i + args.batch_size, len(documents))} / {len(documents)} 文档")
            else:
                print(f"[失败] 导入失败，服务端返回: {result}", file=sys.stderr)
                sys.exit(1)

    print(f"[成功] 共导入 {total} 个文档片段到知识库 '{args.collection}'")


def _load_dataset_corpus(dataset_name: str) -> list[Document]:
    """加载 BEIR 数据集语料，转为 Document 列表（content=title+text，metadata 带 doc_id）。"""
    try:
        corpus = load_corpus(dataset_name)
    except Exception as e:
        print(f"[错误] 加载数据集 {dataset_name} 失败: {e}", file=sys.stderr)
        print("[提示] 若数据集未缓存，请用 HF_HUB_OFFLINE=0 重新运行以下载", file=sys.stderr)
        sys.exit(1)
    return [
        Document(content=f"{row['title']}\n{row['text']}", metadata={"doc_id": row["id"]})
        for row in corpus
    ]


def _ensure_collection(host: str, name: str):
    """collection 不存在则创建（已存在则忽略）。"""
    try:
        rsp = httpx.post(
            f"{host.rstrip('/')}/knowledge",
            json={"name": name, "enabled": True, "hybrid": True},
            timeout=30,
        )
        data = rsp.json()
    except httpx.HTTPError as e:
        print(f"[错误] 创建 collection 失败: {e}", file=sys.stderr)
        sys.exit(1)
    code = (data or {}).get("error_code")
    if code and code != "COLLECTION_EXISTS":
        print(f"[失败] 创建 collection: {data}", file=sys.stderr)
        sys.exit(1)
    if data.get("success"):
        print(f"[信息] 已创建 collection '{name}'")


if __name__ == "__main__":
    main()
