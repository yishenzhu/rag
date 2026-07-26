import re
import numpy as np
from ..core import Document, Chunk


class RecursiveChunker:
    def __init__(self, chunk_size: int, chunk_overlap: int):
        self._chunk_size = chunk_size or 512
        self._chunk_overlap = chunk_overlap or 64

    def split(self, doc: Document) -> list[Chunk]:
        seprators = ["\n\n", "\n", "。", ".", " "]
        parts = self._recursive_split(doc.content, seprators)
        return _build_chunks(parts, doc)

    def _recursive_split(self, text: str, seprators: list[str]) -> list[str]:
        if len(text) <= self._chunk_size:
            return [text]

        if not seprators:
            return self._fixed_split(text)

        splitted: list[str] = []

        sep = seprators[0]
        parts = text.split(sep)
        chunk = ""
        for part in parts:
            join = chunk + sep + part if chunk else part
            if len(join) <= self._chunk_size:
                chunk = join
            else:
                if chunk:
                    splitted.append(chunk)

                if len(part) > self._chunk_size:
                    splitted.extend(self._recursive_split(part, seprators[1:]))
                    chunk = ""
                else:
                    chunk = part
        if chunk:
            splitted.append(chunk)
        return splitted

    def _fixed_split(self, text: str) -> list[str]:
        parts = []
        bgn = 0
        while bgn < len(text) - self._chunk_overlap:
            end = bgn + self._chunk_size
            parts.append(text[bgn:end])
            bgn = end - self._chunk_overlap
        return parts


class SemanticChunker:
    """语义切分：用相邻句子的 embedding 余弦相似度找断点。

    算法：
    1. 按中英文标点拆句
    2. 批量编码所有句子
    3. 计算相邻句子对的余弦相似度
    4. 低于分位数阈值的句子之间视为断点
    5. 合并断点之间的句子，同时遵守最大 chunk_size
    """

    def __init__(
        self,
        chunk_size: int = 512,
        embed_client=None,
        percentile: float = 50.0,
    ):
        self._chunk_size = chunk_size
        self._embed = embed_client
        self._percentile = percentile  # 低于此分位数的相似度视为断点

    def split(self, doc: Document) -> list[Chunk]:
        sentences = self._split_sentences(doc.content)
        if len(sentences) <= 1:
            return self._build_chunks([doc.content], doc)

        # 批量编码
        dense, _ = self._embed.encode(sentences)

        # 相邻句子相似度
        sims = np.array(
            [
                _cosine_sim(dense[i], dense[i + 1])
                for i in range(len(sentences) - 1)
            ]
        )

        # 动态阈值：低于分位数的位置就是断点
        threshold = float(np.percentile(sims, self._percentile))

        # 按断点合并句子
        merged = self._merge_sentences(sentences, sims, threshold)
        return self._build_chunks(merged, doc)

    # ── 内部方法 ────────────────────────────────────────────

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        """拆句，兼容中英文句末标点。"""
        parts = re.split(r"(?<=[。！？.!?；;])\s*", text)
        return [p.strip() for p in parts if p.strip()]

    def _merge_sentences(
        self,
        sentences: list[str],
        sims: np.ndarray,
        threshold: float,
    ) -> list[str]:
        """沿着低相似度断点合并句子，同时遵守 chunk_size 硬上限。"""
        chunks: list[str] = []
        current = sentences[0]

        for i in range(1, len(sentences)):
            candidate = current + " " + sentences[i]
            # 两种情况触发断点：1) 语义不连续  2) 长度将超标
            if sims[i - 1] < threshold or len(candidate) > self._chunk_size:
                chunks.append(current)
                current = sentences[i]
            else:
                current = candidate

        if current:
            chunks.append(current)
        return chunks

    def _build_chunks(self, parts: list[str], doc: Document) -> list[Chunk]:
        return _build_chunks(parts, doc)


# ── 共享工具 ────────────────────────────────────────────────

def _build_chunks(parts: list[str], doc: Document) -> list[Chunk]:
    source = doc.metadata.get("name")
    doc_id = doc.metadata.get("doc_id")
    result: list[Chunk] = []
    for part in parts:
        meta = {}
        if source:
            meta["source"] = source
        if doc_id:
            meta["doc_id"] = doc_id
        result.append(Chunk(content=part, metadata=meta))
    return result


def _cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    dot = float(np.dot(a, b))
    norm = float(np.linalg.norm(a)) * float(np.linalg.norm(b))
    return dot / norm if norm > 0 else 0.0
