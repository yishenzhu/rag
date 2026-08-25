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

    async def split(self, doc: Document) -> list[Chunk]:
        sentences = self._split_sentences(doc.content)
        if len(sentences) <= 1:
            return self._build_chunks([doc.content], doc)

        # 批量编码
        dense, _ = await self._embed.encode(sentences)

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


class MarkdownChunker:
    """按 Markdown 标题层级切分，保语义完整。

    算法：
    1. 逐行扫描，用标题栈维护章节层级（同级/更浅标题弹出深层）
    2. 代码块（```/~~~）内不识别标题，整块保护不切碎
    3. 每个章节成为一个候选 chunk，metadata 带完整标题链
    4. 章节超过 chunk_size 时递归下沉到子标题继续切
    5. 最细粒度仍超长时用 RecursiveChunker 字符级兜底
    """

    def __init__(self, chunk_size: int = 512, chunk_overlap: int = 64):
        self._chunk_size = chunk_size or 512
        self._chunk_overlap = chunk_overlap or 64

    def split(self, doc: Document) -> list[Chunk]:
        sections = self._build_tree(doc.content)
        parts: list[Chunk] = []
        for section in sections:
            parts.extend(self._chunk_section(section, doc))
        return parts

    def _chunk_section(self, section: dict, doc: Document) -> list[Chunk]:
        """一个章节节点 -> Chunk 列表。整节超长时递归下沉子标题，最细兜底。

        section["content"] 是该章节自身正文（不含子章节、不含标题行）。
        整节长度 = 自身正文 + 所有子章节（标题行+正文）。
        """
        parts = [section["content"]]
        parts += [MarkdownChunker._section_text(sub) for sub in section["children"]]
        whole = "\n".join(p for p in parts if p)
        if len(whole) <= self._chunk_size:
            return [self._make_chunk(whole, doc, section["header_chain"])]

        # 整节超长：先切自身正文（若超长），再下沉各子标题
        out: list[Chunk] = []
        if section["content"]:
            out.extend(self._split_own_content(section, doc))
        for sub in section["children"]:
            out.extend(self._chunk_section(sub, doc))
        return out

    @staticmethod
    def _section_text(section: dict) -> str:
        """一节的完整字符串（标题行 + 自身正文 + 子章节）。"""
        parts = []
        if section["header_line"]:
            parts.append(section["header_line"])
        if section["content"]:
            parts.append(section["content"])
        for sub in section["children"]:
            sub_text = MarkdownChunker._section_text(sub)
            if sub_text:
                parts.append(sub_text)
        return "\n".join(parts)

    def _split_own_content(self, section: dict, doc: Document) -> list[Chunk]:
        """切分章节自身的超长正文（不含子标题）。最细粒度字符级兜底。"""
        if len(section["content"]) <= self._chunk_size:
            return [self._make_chunk(section["content"], doc, section["header_chain"])]
        fallback = RecursiveChunker(self._chunk_size, self._chunk_overlap)
        # 只切正文本身，标题已进 metadata 的 headers，不重复进正文
        targets = fallback.split(Document(content=section["content"]))
        parts = [t.content for t in targets]
        return [self._make_chunk(p, doc, section["header_chain"]) for p in parts]

    def _build_tree(self, text: str) -> list[dict]:
        """逐行扫描建章节树；代码块内不识别标题。返回根节点列表。"""
        heading_re = re.compile(r"^(#{1,6})\s+(.*)$")
        code_fences = ("```", "~~~")
        lines = text.split("\n")
        roots: list[dict] = []
        stack: list[dict] = []   # 祖先链，栈顶 = 当前最深章节
        in_code = False
        fence = ""
        buf: list[str] = []      # 待归属的正文（属于当前章节）

        def pop_to(level: int) -> None:
            while stack and stack[-1]["level"] >= level:
                stack.pop()

        def flush(level: int, title: str, header_line: str) -> None:
            content = "\n".join(buf).strip("\n")
            buf.clear()
            pop_to(level)
            chain = tuple(s["title"] for s in stack) + (title,)
            node = {
                "level": level,
                "title": title,
                "content": content,
                "header_line": header_line,
                "header_chain": chain,
                "children": [],
            }
            if stack:
                stack[-1]["children"].append(node)
            else:
                roots.append(node)
            stack.append(node)

        def append_buf() -> None:
            if stack:
                stack[-1]["content"] += "\n".join(buf)
            buf.clear()

        for line in lines:
            stripped = line.strip()
            if not in_code and (
                stripped.startswith(code_fences[0]) or stripped.startswith(code_fences[1])
            ):
                fence = stripped[:3]
                in_code = True
                buf.append(line)
                continue
            if in_code:
                if stripped.startswith(fence):
                    in_code = False
                    fence = ""
                buf.append(line)
                continue
            m = heading_re.match(stripped)
            if m:
                append_buf()
                flush(len(m.group(1)), m.group(2), stripped)
            else:
                buf.append(line)

        append_buf()
        if not roots and buf:
            content = "\n".join(buf).strip("\n")
            buf.clear()
            roots.append({
                "level": 1, "title": "", "content": content,
                "header_line": "", "header_chain": ("",), "children": [],
            })
        return roots

    @staticmethod
    def _make_chunk(
        content: str, doc: Document, header_chain: tuple[str, ...]
    ) -> Chunk:
        """构造 Chunk：继承 doc 元信息 + 标题链 headers。"""
        meta = doc.metadata.copy()
        if header_chain:
            meta["headers"] = list(header_chain)
        return Chunk(content=content, metadata=meta)


# ── 共享工具 ───────────────────────────────────────────────


def _build_chunks(parts: list[str], doc: Document) -> list[Chunk]:
    return [Chunk(content=part, metadata=doc.metadata.copy()) for part in parts]


def _cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    dot = float(np.dot(a, b))
    norm = float(np.linalg.norm(a)) * float(np.linalg.norm(b))
    return dot / norm if norm > 0 else 0.0
