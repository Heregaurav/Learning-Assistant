import re
from typing import Any

from .chunker import chunk_text, select_context_chunks
from .parser import ParsedDocument, parse_document


class DocumentProcessingService:
    @staticmethod
    def normalize_document_text(text: str) -> str:
        cleaned = re.sub(r"\r\n?", "\n", text)
        cleaned = re.sub(r"\t+", " ", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
        cleaned = cleaned.strip()
        return cleaned

    @staticmethod
    def process_uploaded_document(
        *, filename: str, content_type: str, file_bytes: bytes, source_name: str | None = None
    ) -> ParsedDocument:
        parsed = parse_document(filename, content_type, file_bytes, source_name=source_name)
        parsed.text = DocumentProcessingService.normalize_document_text(parsed.text)
        return parsed

    @staticmethod
    def build_context_for_llm(document: ParsedDocument, *, max_words: int = 3000) -> str:
        chunks = chunk_text(document.text)
        selected = select_context_chunks(chunks, max_chunks=5)
        if not selected:
            return document.text[:max_words]
        return selected[:max_words]

    @staticmethod
    def document_metadata(document: ParsedDocument) -> dict[str, Any]:
        return {
            "title": document.title,
            "filename": document.source_name,
            "extension": document.extension,
            "mime_type": document.mime_type,
            "word_count": document.word_count,
            "page_count": document.page_count,
            "warnings": document.warnings,
        }
