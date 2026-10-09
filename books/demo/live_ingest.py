"""Live PDF ingest for the local demo.

Same Stage 1 chunking and BGE-M3 hybrid indexes the demo already searches.
Does not re-run E5 Stage 2, does not overwrite reserved books, and does not
change frozen evaluation artifacts.
"""

from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path
from typing import Any, Callable

from db import (
    apply_schema,
    connect,
    upsert_bge_m3_embeddings,
    upsert_bge_m3_hybrid_sparse_weights,
    upsert_book,
    upsert_chunks,
)
from embed_bge_m3_dense import BGE_MODEL, embed_texts, validate_embeddings
from ingest_stage1 import load_pdf_pages
from chunking import (
    DEFAULT_CONTENT_CHUNK_OVERLAP,
    DEFAULT_CONTENT_CHUNK_SIZE,
    e5_input_token_count,
    split_documents_e5_safe,
)
from report import chunks_artifact_payload

StatusFn = Callable[[str, str], None]


def sanitize_stem(name: str) -> str:
    stem = Path(name or "book").stem.strip().lower()
    stem = re.sub(r"[^a-z0-9]+", "_", stem).strip("_")
    return (stem[:40] or "book")


def make_live_book_id(original_name: str, pdf_bytes: bytes, reserved: set[str]) -> str:
    digest = hashlib.sha256(pdf_bytes).hexdigest()[:8]
    base = f"live_{sanitize_stem(original_name)}_{digest}"
    if base not in reserved:
        return base
    n = 2
    while f"{base}_{n}" in reserved:
        n += 1
    return f"{base}_{n}"


def short_label_from_filename(name: str) -> str:
    stem = Path(name or "Attached PDF").stem.replace("_", " ").replace("-", " ").strip()
    return stem[:48] or "Attached PDF"


def spine_from_label(label: str) -> str:
    letters = re.findall(r"[A-Za-z0-9]", label or "")
    if len(letters) >= 2:
        return (letters[0] + letters[1]).upper()
    if letters:
        return letters[0].upper()
    return "+"


def chunk_digital_pdf(
    pdf_path: Path,
    *,
    book_id: str,
    original_name: str,
    tokenizer,
    max_pages: int,
    max_chunks: int,
    status: StatusFn | None = None,
) -> dict[str, Any]:
    if status:
        status("extract", "Reading text from the PDF…")
    pages, extraction = load_pdf_pages(pdf_path)
    total_pages = int(extraction.get("total_pages") or 0)
    if total_pages > max_pages:
        raise ValueError(
            f"This PDF has {total_pages} pages. For a live attach, use at most {max_pages} pages "
            "(digital text, not a scan)."
        )
    if not pages:
        raise ValueError(
            "No extractable text. This demo only indexes digital-text PDFs (no OCR)."
        )
    # Keep the live book_id; do not let the filename invent a reserved id.
    for page in pages:
        page.metadata["book_id"] = book_id
        page.metadata["filename"] = original_name
        page.metadata["source"] = str(pdf_path)

    if status:
        status("chunk", "Splitting the PDF into passages…")
    chunks, _stats = split_documents_e5_safe(
        pages,
        tokenizer,
        chunk_size=DEFAULT_CONTENT_CHUNK_SIZE,
        chunk_overlap=DEFAULT_CONTENT_CHUNK_OVERLAP,
    )
    for doc in chunks:
        doc.metadata["book_id"] = book_id
        doc.metadata["filename"] = original_name
        doc.metadata["source"] = str(pdf_path)
        actual = e5_input_token_count(tokenizer, doc.page_content)
        if actual != doc.metadata["e5_input_token_count"]:
            raise RuntimeError("Stored e5_input_token_count does not match tokenizer.")
        if actual > 512:
            raise RuntimeError("A chunk still exceeds the 512-token gate.")
    if not chunks:
        raise ValueError("The PDF produced no passages after chunking.")
    if len(chunks) > max_chunks:
        raise ValueError(
            f"This PDF produced {len(chunks)} passages. For a live attach, use a shorter book "
            f"(at most {max_chunks} passages)."
        )
    payload = chunks_artifact_payload(
        pdf_path=pdf_path,
        book_id=book_id,
        extraction=extraction,
        chunks=chunks,
    )
    payload["filename"] = original_name
    return payload


def store_chunks_without_e5(payload: dict[str, Any]) -> None:
    """Write chunk text/pages for hybrid search. Leaves E5 vectors null on purpose."""
    book_id = payload["book_id"]
    rows = []
    for rec in payload["chunks"]:
        idx = int(rec["chunk_index"])
        rows.append(
            {
                "id": f"{book_id}:{idx}",
                "book_id": book_id,
                "page": rec.get("page"),
                "chunk_index": idx,
                "chunk_text": rec["text"],
                "content_token_count": rec.get("content_token_count"),
                "e5_input_token_count": rec.get("e5_input_token_count"),
                "embedding": None,
            }
        )
    conn = connect()
    try:
        apply_schema(conn)
        upsert_book(
            conn,
            book_id=book_id,
            filename=payload.get("filename") or "",
            source=payload.get("source"),
            total_pages=payload.get("total_pages"),
        )
        upsert_chunks(conn, rows)
    finally:
        conn.close()


def index_bge_m3_hybrid(
    payload: dict[str, Any],
    *,
    dense_model,
    sparse_encoder,
    status: StatusFn | None = None,
) -> dict[str, float]:
    records = payload["chunks"]
    book_id = payload["book_id"]
    texts = [r["text"] for r in records]
    t0 = time.perf_counter()
    if status:
        status("dense", f"Embedding {len(texts)} passages with BGE-M3…")
    embeddings = embed_texts(dense_model, texts, batch_size=8, device="cpu")
    validate_embeddings(embeddings, len(texts))
    dense_s = time.perf_counter() - t0
    dense_rows = [
        {
            "book_id": book_id,
            "chunk_index": int(rec["chunk_index"]),
            "embedding": vec.tolist(),
            "model_name": BGE_MODEL,
        }
        for rec, vec in zip(records, embeddings)
    ]
    conn = connect()
    try:
        upsert_bge_m3_embeddings(conn, dense_rows)
    finally:
        conn.close()

    t1 = time.perf_counter()
    if status:
        status("sparse", "Building the hybrid sparse index…")
    weights_list = sparse_encoder.encode_lexical_weights(texts, batch_size=4)
    sparse_s = time.perf_counter() - t1
    sparse_rows = [
        {
            "book_id": book_id,
            "chunk_index": int(rec["chunk_index"]),
            "lexical_weights": weights,
            "n_nonzero": len(weights),
            "model_name": BGE_MODEL,
        }
        for rec, weights in zip(records, weights_list)
    ]
    conn = connect()
    try:
        upsert_bge_m3_hybrid_sparse_weights(conn, sparse_rows)
    finally:
        conn.close()
    return {"dense_s": dense_s, "sparse_s": sparse_s}
