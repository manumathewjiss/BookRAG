"""Stage 1 validation report writer. Storage-independent JSON only."""

from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any

from langchain_core.documents import Document


def _token_stats(values: list[int]) -> dict[str, float | int | None]:
    if not values:
        return {"minimum": None, "average": None, "median": None, "maximum": None, "n": 0}
    return {
        "minimum": min(values),
        "average": round(sum(values) / len(values), 2),
        "median": statistics.median(values),
        "maximum": max(values),
        "n": len(values),
    }


def _preview(text: str, n: int = 400) -> str:
    t = " ".join((text or "").split())
    return t if len(t) <= n else t[: n - 1] + "…"


def build_report(
    *,
    pdf_path: Path,
    book_id: str,
    extraction: dict[str, Any],
    chunks: list[Document],
    chunk_stats: dict[str, Any],
    overhead: dict[str, int],
    extra_warnings: list[str],
) -> dict[str, Any]:
    content_counts = [int(d.metadata["content_token_count"]) for d in chunks]
    e5_counts = [int(d.metadata["e5_input_token_count"]) for d in chunks]
    n_final_over = sum(1 for n in e5_counts if n > 512)

    sample_chunks = []
    if chunks:
        sample_idxs = {0, len(chunks) // 2, len(chunks) - 1}
        for i in sorted(sample_idxs):
            d = chunks[i]
            sample_chunks.append(
                {
                    "chunk_index": d.metadata.get("chunk_index"),
                    "page": d.metadata.get("page"),
                    "content_token_count": d.metadata.get("content_token_count"),
                    "e5_input_token_count": d.metadata.get("e5_input_token_count"),
                    "text_preview": _preview(d.page_content),
                }
            )

    metadata_examples = [dict(d.metadata) for d in chunks[:3]]

    warnings = list(extraction.get("warnings") or [])
    warnings.extend(chunk_stats.get("warnings") or [])
    warnings.extend(extra_warnings)

    return {
        "stage": 1,
        "pipeline": (
            "digital-text PDF → PyPDFLoader → Documents → light clean → "
            "E5-token-aware RecursiveCharacterTextSplitter → validate → STOP"
        ),
        "not_implemented": [
            "embeddings",
            "FAISS",
            "PostgreSQL/pgvector",
            "Qwen/Ollama",
            "OCR",
        ],
        "pdf": {
            "filename": pdf_path.name,
            "book_id": book_id,
            "path": str(pdf_path),
            "total_pages": extraction["total_pages"],
            "pages_with_extractable_text": extraction["pages_with_extractable_text"],
            "empty_pages": extraction["empty_pages"],
            "empty_page_numbers": extraction["empty_page_numbers"],
            "total_extracted_characters": extraction["total_extracted_characters"],
        },
        "tokenizer": {
            "model": "intfloat/multilingual-e5-large",
            "hard_e5_input_limit": 512,
            "target_content_chunk_size": chunk_stats["target_content_chunk_size"],
            "target_content_chunk_overlap": chunk_stats["target_content_chunk_overlap"],
            "measured_prefix_special_token_overhead": overhead,
        },
        "chunks": {
            "total_chunks": len(chunks),
            "n_first_pass_chunks": chunk_stats["n_first_pass_chunks"],
            "n_chunks_initially_exceeding_512": chunk_stats[
                "n_chunks_initially_exceeding_512"
            ],
            "n_final_chunks_exceeding_512": n_final_over,
            "content_token_statistics": _token_stats(content_counts),
            "e5_input_token_statistics": _token_stats(e5_counts),
        },
        "metadata_examples": metadata_examples,
        "sample_chunks": sample_chunks,
        "warnings": warnings,
    }


def write_report(report: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def chunks_artifact_payload(
    *,
    pdf_path: Path,
    book_id: str,
    extraction: dict[str, Any],
    chunks: list[Document],
) -> dict[str, Any]:
    """
    Persist the exact validated Stage 1 chunks for Stage 2.

    This does not change chunking. It only serializes the in-memory
    Documents that already passed the E5 512-token gate.
    """
    records = []
    for d in chunks:
        records.append(
            {
                "book_id": d.metadata.get("book_id", book_id),
                "filename": d.metadata.get("filename", pdf_path.name),
                "source": d.metadata.get("source", str(pdf_path)),
                "page": d.metadata.get("page"),
                "chunk_index": d.metadata["chunk_index"],
                "text": d.page_content,
                "content_token_count": d.metadata["content_token_count"],
                "e5_input_token_count": d.metadata["e5_input_token_count"],
            }
        )
    return {
        "stage": 1,
        "artifact": "validated_chunks",
        "book_id": book_id,
        "filename": pdf_path.name,
        "source": str(pdf_path),
        "total_pages": extraction["total_pages"],
        "pages_with_extractable_text": extraction["pages_with_extractable_text"],
        "empty_pages": extraction["empty_pages"],
        "total_extracted_characters": extraction["total_extracted_characters"],
        "chunk_count": len(records),
        "chunks": records,
    }


def write_chunks_artifact(payload: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
