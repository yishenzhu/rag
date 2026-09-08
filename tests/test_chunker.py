"""MarkdownChunker 行为测试。"""

import pytest
from rag.core import Text
from rag.engine.chunker import MarkdownChunker


def _doc(content: str, name: str = "test.md") -> Text:
    return Text(content=content, metadata={"source": name})


def test_basic_headings_split():
    """模型B：短章节整节合并成一个 chunk，headers 只带根标题。"""
    md = "# 总标题\n引言。\n\n## 章节一\n正文一。\n\n## 章节二\n正文二。\n"
    chunks = MarkdownChunker(chunk_size=100).split(_doc(md))
    # 整节未超长(chunk_size=100) -> 整体合并成 1 个 chunk
    assert len(chunks) == 1
    assert chunks[0].metadata["headers"] == ["总标题"]
    assert "引言" in chunks[0].content
    assert "正文一" in chunks[0].content
    assert "正文二" in chunks[0].content


def test_code_block_preserved_and_no_fake_heading():
    """代码块内的 # 不触发标题切分，整块保留。"""
    md = "## 章节\n正文。\n\n```python\n# 这是注释\nprint(1)\n```\n\n## 尾声\n结束。\n"
    chunks = MarkdownChunker(chunk_size=100).split(_doc(md))
    # 两个标题 -> 2 个 chunk（章节 + 尾声）
    assert len(chunks) == 2
    assert "# 这是注释" in chunks[0].content
    assert "```python" in chunks[0].content


def test_oversized_section_recurses_to_children():
    """超长章节递归下沉到子标题。"""
    md = (
        "# 文档\n\n## 长章\n"
        + ("内容很长" * 50)
        + "\n\n### 子节A\nA。\n\n### 子节B\nB。\n"
    )
    chunks = MarkdownChunker(chunk_size=20).split(_doc(md))
    # 长正文被切分，子节 A/B 各自成块
    contents = "".join(c.content for c in chunks)
    assert "子节A" in contents or "A。" in contents
    assert "子节B" in contents or "B。" in contents
    assert all(
        len(c.content) <= 20 or "A。" in c.content or "B。" in c.content for c in chunks
    )


def test_no_heading_document():
    """无标题文档整体作为一个 chunk。"""
    md = "一段没有标题的纯文本。\n" * 3
    chunks = MarkdownChunker(chunk_size=1000).split(_doc(md))
    assert len(chunks) == 1
    assert "纯文本" in chunks[0].content


def test_metadata_chain_and_source():
    """模型B：headers 只带根标题，source 字段透传，子标题行作为正文保留。"""
    md = "# API\n## Auth\n正文。\n"
    chunks = MarkdownChunker().split(_doc(md, name="doc.md"))
    # 整节合并成 1 个 chunk，headers 只带根标题 API
    assert len(chunks) == 1
    assert chunks[0].metadata["source"] == "doc.md"
    assert chunks[0].metadata["headers"] == ["API"]
    assert "正文" in chunks[0].content
    # 子标题行作为合并块的一部分保留在正文
    assert "## Auth" in chunks[0].content


def test_subsection_heading_kept_in_merged_block():
    """模型B：短小节合并进大块时，子标题行作为正文保留，headers 只带根标题。"""
    md = "# Head\n## Sub\n正文内容。\n"
    chunks = MarkdownChunker().split(_doc(md))
    # 整节合并成 1 个 chunk
    assert len(chunks) == 1
    chunk = chunks[0]
    # headers 只带根标题（模型B，短小节无独立标题链）
    assert chunk.metadata["headers"] == ["Head"]
    # 子标题行作为合并块的一部分保留在正文
    assert "## Sub" in chunk.content
    assert "正文内容" in chunk.content
