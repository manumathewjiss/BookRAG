"""
Stage 1: digital-text PDF → LangChain Documents → E5-safe chunks → validation report.

No embeddings, FAISS, pgvector, OCR, or Qwen.
Does not touch gita/ or src/.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from langchain_community.document_loaders import PyPDFLoader
from langchain_core.documents import Document

from chunking import (
    DEFAULT_CONTENT_CHUNK_OVERLAP,
    DEFAULT_CONTENT_CHUNK_SIZE,
    e5_input_token_count,
    load_e5_tokenizer,
    measure_prefix_overhead,
    split_documents_e5_safe,
)
from report import (
    build_report,
    chunks_artifact_payload,
    write_chunks_artifact,
    write_report,
)

ROOT = Path(__file__).resolve().parent
SAMPLE_DIR = ROOT / "sample_pdfs"
OUTPUT_DIR = ROOT / "outputs"


def book_id_from_path(pdf_path: Path) -> str:
    stem = pdf_path.stem.strip().lower()
    stem = re.sub(r"[^a-z0-9]+", "_", stem).strip("_")
    return stem or "book"


def clean_page_text(text: str) -> str:
    """Light cleanup only: keep paragraph breaks, collapse runaway whitespace."""
    if not text:
        return ""
    text = text.replace("\x00", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def normalize_page_number(raw: object) -> int | None:
    """LangChain/pypdf page metadata is often 0-based. Store 1-based page numbers."""
    if raw is None:
        return None
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return None
    return n + 1 if n >= 0 else n


def load_pdf_pages(pdf_path: Path) -> tuple[list[Document], dict]:
    loader = PyPDFLoader(str(pdf_path), mode="page")
    raw_docs = loader.load()
    warnings: list[str] = []
    pages: list[Document] = []
    empty_page_numbers: list[int] = []
    total_chars = 0

    for doc in raw_docs:
        page = normalize_page_number(doc.metadata.get("page"))
        cleaned = clean_page_text(doc.page_content or "")
        if not cleaned:
            if page is not None:
                empty_page_numbers.append(page)
            warnings.append(
                f"Page {page} has no extractable text (digital-text loader only; no OCR)."
            )
            continue
        total_chars += len(cleaned)
        pages.append(
            Document(
                page_content=cleaned,
                metadata={
                    "source": str(pdf_path),
                    "filename": pdf_path.name,
                    "book_id": book_id_from_path(pdf_path),
                    "page": page,
                },
            )
        )

    total_pages = len(raw_docs)
    extraction = {
        "total_pages": total_pages,
        "pages_with_extractable_text": len(pages),
        "empty_pages": len(empty_page_numbers),
        "empty_page_numbers": empty_page_numbers,
        "total_extracted_characters": total_chars,
        "warnings": warnings,
    }
    if total_pages == 0:
        warnings.append("PDF loader returned zero pages.")
    if pages and total_chars < 200:
        warnings.append(
            "Very little text extracted. This PDF may be scanned/image-only; OCR is out of scope."
        )
    return pages, extraction


def attach_book_metadata(chunks: list[Document], pdf_path: Path) -> None:
    book_id = book_id_from_path(pdf_path)
    for doc in chunks:
        doc.metadata["source"] = str(pdf_path)
        doc.metadata["filename"] = pdf_path.name
        doc.metadata["book_id"] = book_id


def run(
    pdf_path: Path,
    output_path: Path | None = None,
    chunk_size: int = DEFAULT_CONTENT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CONTENT_CHUNK_OVERLAP,
) -> dict:
    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    print(f"Loading tokenizer intfloat/multilingual-e5-large (tokenizer only)...")
    tokenizer = load_e5_tokenizer()
    overhead = measure_prefix_overhead(tokenizer)
    print("Measured prefix/special-token overhead:", overhead)

    print(f"Loading PDF with LangChain PyPDFLoader: {pdf_path}")
    pages, extraction = load_pdf_pages(pdf_path)
    print(
        f"Pages={extraction['total_pages']} "
        f"with_text={extraction['pages_with_extractable_text']} "
        f"empty={extraction['empty_pages']} "
        f"chars={extraction['total_extracted_characters']}"
    )

    extra_warnings: list[str] = []
    if not pages:
        extra_warnings.append("No extractable text pages; no chunks produced.")
        chunks, chunk_stats = [], {
            "n_first_pass_chunks": 0,
            "n_chunks_initially_exceeding_512": 0,
            "n_final_chunks": 0,
            "n_final_chunks_exceeding_512": 0,
            "target_content_chunk_size": chunk_size,
            "target_content_chunk_overlap": chunk_overlap,
            "warnings": [],
        }
    else:
        chunks, chunk_stats = split_documents_e5_safe(
            pages, tokenizer, chunk_size=chunk_size, chunk_overlap=chunk_overlap
        )
        attach_book_metadata(chunks, pdf_path)

    n_final_over = sum(
        1 for d in chunks if int(d.metadata["e5_input_token_count"]) > 512
    )
    if n_final_over:
        raise RuntimeError(f"{n_final_over} final chunks still exceed E5's 512-token limit.")

    # Sanity: authoritative count matches stored metadata.
    for d in chunks:
        actual = e5_input_token_count(tokenizer, d.page_content)
        if actual != d.metadata["e5_input_token_count"]:
            raise RuntimeError("Stored e5_input_token_count does not match tokenizer.")

    report = build_report(
        pdf_path=pdf_path,
        book_id=book_id_from_path(pdf_path),
        extraction=extraction,
        chunks=chunks,
        chunk_stats=chunk_stats,
        overhead=overhead,
        extra_warnings=extra_warnings,
    )
    if output_path is None:
        output_path = OUTPUT_DIR / f"{book_id_from_path(pdf_path)}_stage1_validation.json"
    write_report(report, output_path)
    print(f"Wrote {output_path}")

    # Additive handoff for Stage 2: exact validated chunks, same in-memory list.
    chunks_path = OUTPUT_DIR / f"{book_id_from_path(pdf_path)}_stage1_chunks.json"
    write_chunks_artifact(
        chunks_artifact_payload(
            pdf_path=pdf_path,
            book_id=book_id_from_path(pdf_path),
            extraction=extraction,
            chunks=chunks,
        ),
        chunks_path,
    )
    print(f"Wrote {chunks_path}")
    print(
        "chunks={total} initially_over_512={init} final_over_512={final}".format(
            total=report["chunks"]["total_chunks"],
            init=report["chunks"]["n_chunks_initially_exceeding_512"],
            final=report["chunks"]["n_final_chunks_exceeding_512"],
        )
    )
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Stage 1: extract and E5-safe-chunk a digital-text PDF."
    )
    p.add_argument("--pdf", type=Path, required=True, help="Path to a digital-text PDF.")
    p.add_argument("--output", type=Path, default=None)
    p.add_argument("--chunk-size", type=int, default=DEFAULT_CONTENT_CHUNK_SIZE)
    p.add_argument("--chunk-overlap", type=int, default=DEFAULT_CONTENT_CHUNK_OVERLAP)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    run(
        pdf_path=args.pdf.expanduser().resolve(),
        output_path=args.output.expanduser().resolve() if args.output else None,
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
