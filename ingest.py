import argparse
import sys
import httpx

from .rag import DocumentLoader


def main():
    parser = argparse.ArgumentParser(description="加载文档并导入到本地 RAG 知识库")
    parser.add_argument("source", help="文档文件或目录路径")
    parser.add_argument("-c", "--collection", required=True, help="目标知识库名称")
    parser.add_argument(
        "--host",
        default="http://localhost:8001",
        help="RAG 服务地址（默认 http://localhost:8001）",
    )
    parser.add_argument(
        "--chunk-size", type=int, default=None, help="分块大小（默认由服务端决定）"
    )
    parser.add_argument(
        "--chunk-overlap",
        type=int,
        default=None,
        help="分块重叠大小（默认由服务端决定）",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=512,
        help="每批次导入文档数（默认 512）",
    )

    args = parser.parse_args()

    loader = DocumentLoader()
    try:
        documents = loader.load(args.source)
    except FileNotFoundError as e:
        print(f"[错误] {e}", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(f"[错误] {e}", file=sys.stderr)
        sys.exit(1)

    if not documents:
        print("[提示] 未找到任何可导入的文档")
        sys.exit(0)

    print(f"[信息] 共加载 {len(documents)} 个文档，正在分批发送至 RAG 服务...")

    url = f"{args.host.rstrip('/')}/knowledge/ingest"
    batch_size = args.batch_size
    total_ingested = 0

    with httpx.Client(timeout=120) as client:
        for i in range(0, len(documents), batch_size):
            batch = documents[i : i + batch_size]
            payload = {
                "collection": args.collection,
                "documents": [doc.model_dump() for doc in batch],
            }
            if args.chunk_size is not None:
                payload["chunk_size"] = args.chunk_size
            if args.chunk_overlap is not None:
                payload["chunk_overlap"] = args.chunk_overlap

            try:
                rsp = client.post(url, json=payload)
                rsp.raise_for_status()
                result = rsp.json()
            except httpx.HTTPError as e:
                print(f"[错误] 请求 RAG 服务失败: {e}", file=sys.stderr)
                sys.exit(1)

            if result.get("success"):
                total_ingested += result.get("count", len(batch))
                print(
                    f"[信息] 已导入 {min(i + batch_size, len(documents))} / {len(documents)} 文档"
                )
            else:
                print(f"[失败] 导入失败，服务端返回: {result}", file=sys.stderr)
                sys.exit(1)

    print(f"[成功] 共导入 {total_ingested} 个文档片段到知识库 '{args.collection}'")


if __name__ == "__main__":
    main()
