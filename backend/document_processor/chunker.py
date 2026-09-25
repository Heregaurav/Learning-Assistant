import re
from typing import List


MAX_CHUNK_CHARS = 2200


def chunk_text(text: str, *, target_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    cleaned = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not cleaned:
        return []
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", cleaned) if p.strip()]
    if not paragraphs:
        paragraphs = [cleaned]

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for paragraph in paragraphs:
        if len(paragraph) + current_len + 2 <= target_chars:
            current.append(paragraph)
            current_len += len(paragraph) + 2
            continue
        if current:
            chunks.append("\n\n".join(current))
        if len(paragraph) <= target_chars:
            current = [paragraph]
            current_len = len(paragraph)
        else:
            sentences = re.split(r"(?<=[.!?])\s+", paragraph)
            mini: list[str] = []
            mini_len = 0
            for sentence in sentences:
                if len(sentence) + mini_len + 1 <= target_chars:
                    mini.append(sentence)
                    mini_len += len(sentence) + 1
                else:
                    if mini:
                        chunks.append(" ".join(mini))
                    mini = [sentence]
                    mini_len = len(sentence)
            if mini:
                current = mini
                current_len = mini_len
    if current:
        chunks.append("\n\n".join(current))
    return chunks[:12]


def select_context_chunks(chunks: List[str], *, max_chunks: int = 5) -> str:
    if not chunks:
        return ""
    selected = chunks[:1]
    if len(chunks) > 1:
        selected = chunks[: min(max_chunks, len(chunks))]
    return "\n\n---\n\n".join(selected)
