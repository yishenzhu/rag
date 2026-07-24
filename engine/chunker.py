from ..core import Document, Chunk


class RecursiveChunker:
    def __init__(self, chunk_size: int, chunk_overlap: int):
        self._chunk_size = chunk_size or 512
        self._chunk_overlap = chunk_overlap or 64

    def split(self, doc: Document) -> list[Chunk]:
        seprators = ["\n\n", "\n", "。", ".", " "]
        parts = self._recursive_split(doc.content, seprators)
        chunks: list[Chunk] = []
        source = doc.metadata.get("name")
        doc_id = doc.metadata.get("doc_id")
        for part in parts:
            meta = {}
            if source:
                meta["source"] = source
            if doc_id:
                meta["doc_id"] = doc_id
            chunks.append(Chunk(content=part, metadata=meta))
        return chunks

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
