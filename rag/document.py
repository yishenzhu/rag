from pathlib import Path
from markitdown import MarkItDown
import logging
from ..core import Document

DOC_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".doc",
    ".pptx",
    ".xlsx",
    ".xls",
    ".html",
    ".htm",
    ".md",
    ".txt",
    ".csv",
    ".json",
    ".xml",
}

logger = logging.getLogger(__name__)

class DocumentLoader:
    def __init__(self):
        self._converter = MarkItDown()

    def load(self, source: str) -> list[Document]:
        source = Path(source)
        if not source.exists():
            raise FileNotFoundError(f"{source} does not exist")
        if source.is_dir():
            return self._load_dir(source, True)

        suffix = source.suffix.lower()
        if suffix not in DOC_EXTENSIONS:
            raise ValueError(f"Unsupported file type: {suffix}")

        content = (
            self._read_auto_encoding(source)
            if suffix in {".md", ".txt", ".csv", ".json", ".xml"}
            else self._converter.convert(source).text_content
        ).strip()

        if not content:
            return []

        metadata = {
            "name": source.name,
        }
        return [Document(content=content, metadata=metadata)]

    def _read_auto_encoding(self, source: Path) -> str:
        encodings = ["utf-8", "gbk", "gb2312", "latin-1"]

        for encoding in encodings:
            try:
                return source.read_text(encoding=encoding)
            except UnicodeDecodeError:
                logger.info(f"Failed to decode {source} with {encoding}")
                continue
        return ""

    def _load_dir(self, dir: Path, recursive: bool) -> list[Document]:
        docs: list[Document] = []
        pattern = "**/*" if recursive else "*"
        for path in dir.glob(pattern):
            if path.is_file() and path.suffix.lower() in DOC_EXTENSIONS:
                doc = self.load(path)
                docs.extend(doc or [])
        return docs
