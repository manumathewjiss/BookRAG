"""Page-aware text extraction and deterministic token chunks. No local model is loaded."""
from io import BytesIO
import re

import tiktoken
from pypdf import PdfReader


def clean_page_text(text: str) -> str:
    """Match the research pipeline's light whitespace cleanup, without changing meaning."""
    text = (text or "").replace("\x00", " ").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def extract_chunks(pdf_bytes: bytes, max_pages: int, max_passages: int) -> tuple[int, list[dict]]:
    reader = PdfReader(BytesIO(pdf_bytes))
    if reader.is_encrypted or len(reader.pages) > max_pages:
        raise ValueError("PDF is encrypted or exceeds the page limit")
    codec = tiktoken.get_encoding("cl100k_base")
    chunks: list[dict] = []
    for page_no, page in enumerate(reader.pages, start=1):
        text = clean_page_text(page.extract_text() or "")
        if not text.strip():
            continue
        ids = codec.encode(text)
        start = 0
        while start < len(ids):
            fragment = codec.decode(ids[start:start + 450]).strip()
            if fragment:
                chunks.append({"chunk_index": len(chunks), "pdf_page": page_no, "text": fragment})
            if len(chunks) > max_passages:
                raise ValueError("PDF exceeds the passage limit")
            if start + 450 >= len(ids):
                break
            start += 400  # 50-token overlap; stays inside the page for honest citations.
    if not chunks:
        raise ValueError("PDF contains no extractable text")
    return len(reader.pages), chunks
