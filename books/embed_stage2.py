"""
Stage 2: embed validated Stage 1 chunks with E5 and store in PostgreSQL + pgvector.

Consumes the Stage 1 chunks JSON. Does not re-parse or re-chunk the PDF.
Does not implement query retrieval, Qwen, or FAISS.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

from db import (
    apply_schema,
    book_count,
    chunk_count_for_book,
    connect,
    duplicate_chunk_index_count,
    null_embedding_count,
    upsert_book,
    upsert_chunks,
)

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "outputs"
E5_MODEL = "intfloat/multilingual-e5-large"
PASSAGE_PREFIX = "passage: "
EXPECTED_DIM = 1024
E5_MAX_INPUT_TOKENS = 512
NORM_ATOL = 1e-3


def load_stage1_chunks(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("artifact") != "validated_chunks":
        raise ValueError(f"{path} is not a Stage 1 validated_chunks artifact.")
    chunks = payload.get("chunks")
    if not isinstance(chunks, list) or not chunks:
        raise ValueError(f"{path} contains no chunks.")
    return payload


def passage_input(text: str) -> str:
    return PASSAGE_PREFIX + text


def choose_device(requested: str) -> str:
    """Prefer explicit device. Default CPU to match the Gita embedding recipe."""
    if requested != "auto":
        return requested
    return "cpu"


def embed_passages(
    texts: list[str],
    *,
    model_name: str,
    batch_size: int,
    device: str,
) -> np.ndarray:
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    import torch
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(model_name, device=device)
    model.eval()
    inputs = [passage_input(t) for t in texts]
    with torch.inference_mode():
        embeddings = model.encode(
            inputs,
            batch_size=batch_size,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=True,
            device=device,
        )
    return np.asarray(embeddings, dtype=np.float32)


def validate_embeddings(embeddings: np.ndarray, n_chunks: int) -> dict:
    warnings: list[str] = []
    if embeddings.ndim != 2:
        raise RuntimeError(f"Expected 2D embedding matrix, got shape {embeddings.shape}")
    n, dim = embeddings.shape
    n_bad_dim = 0 if dim == EXPECTED_DIM else n
    if n != n_chunks:
        raise RuntimeError(f"Embedded {n} vectors but received {n_chunks} chunks.")
    if dim != EXPECTED_DIM:
        warnings.append(f"Unexpected embedding dimension {dim} (expected {EXPECTED_DIM}).")
    norms = np.linalg.norm(embeddings, axis=1)
    if not np.allclose(norms, 1.0, atol=NORM_ATOL):
        warnings.append(
            f"Vectors are not unit-normalized: min={float(norms.min())} max={float(norms.max())}"
        )
        raise RuntimeError("Embedding L2 norms are not ~1.0; refusing to store.")
    return {
        "n_embeddings": int(n),
        "embedding_dimension": int(dim),
        "expected_dimension": EXPECTED_DIM,
        "n_incorrect_dimension": int(n_bad_dim),
        "normalized_vector_check": "pass",
        "minimum_vector_norm": float(norms.min()),
        "average_vector_norm": float(norms.mean()),
        "maximum_vector_norm": float(norms.max()),
        "warnings": warnings,
    }


def run(
    chunks_path: Path,
    *,
    model_name: str = E5_MODEL,
    batch_size: int = 16,
    device: str = "cpu",
) -> dict:
    t0 = time.perf_counter()
    payload = load_stage1_chunks(chunks_path)
    book_id = payload["book_id"]
    records = payload["chunks"]
    n_received = len(records)

    overs = [r for r in records if int(r["e5_input_token_count"]) > E5_MAX_INPUT_TOKENS]
    if overs:
        raise RuntimeError(
            f"{len(overs)} Stage 1 chunks exceed E5's 512-token input; refusing to truncate."
        )

    texts = [r["text"] for r in records]
    device = choose_device(device)
    print(f"Embedding {n_received} chunks with {model_name} on {device} (passage: prefix)...")
    embeddings = embed_passages(
        texts, model_name=model_name, batch_size=batch_size, device=device
    )
    emb_stats = validate_embeddings(embeddings, n_received)
    print(
        f"dim={emb_stats['embedding_dimension']} "
        f"norm_min={emb_stats['minimum_vector_norm']:.6f} "
        f"norm_max={emb_stats['maximum_vector_norm']:.6f}"
    )

    rows = []
    for rec, vec in zip(records, embeddings):
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
                "embedding": vec.tolist(),
            }
        )

    n_failed = 0
    db_warnings: list[str] = []
    print("Connecting to PostgreSQL / pgvector...")
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
        n_books = book_count(conn)
        n_stored = chunk_count_for_book(conn, book_id)
        n_null = null_embedding_count(conn, book_id)
        n_dup = duplicate_chunk_index_count(conn, book_id)
    finally:
        conn.close()

    elapsed = round(time.perf_counter() - t0, 2)
    warnings = list(emb_stats["warnings"]) + db_warnings
    report = {
        "stage": 2,
        "pipeline": (
            "Stage 1 validated chunks → passage: prefix → multilingual-e5-large → "
            "L2-normalized 1024-D vectors → PostgreSQL/pgvector upsert"
        ),
        "not_implemented": [
            "query embeddings",
            "Top-K retrieval",
            "Qwen/Ollama",
            "ANN indexes (HNSW/IVFFlat)",
            "FAISS",
        ],
        "embedding_model": model_name,
        "device": device,
        "passage_prefix": PASSAGE_PREFIX,
        "chunks_artifact": str(chunks_path),
        "book_id": book_id,
        "total_chunks_received": n_received,
        "total_embeddings_created": emb_stats["n_embeddings"],
        "embedding_dimension": emb_stats["embedding_dimension"],
        "expected_dimension": emb_stats["expected_dimension"],
        "n_incorrect_dimension": emb_stats["n_incorrect_dimension"],
        "normalized_vector_check": emb_stats["normalized_vector_check"],
        "minimum_vector_norm": emb_stats["minimum_vector_norm"],
        "average_vector_norm": emb_stats["average_vector_norm"],
        "maximum_vector_norm": emb_stats["maximum_vector_norm"],
        "database_book_row_count": n_books,
        "database_chunk_row_count_for_book": n_stored,
        "n_null_embeddings": n_null,
        "n_duplicate_chunk_indexes": n_dup,
        "n_failed_embeddings": n_failed,
        "processing_seconds": elapsed,
        "idempotency": "upsert on books.book_id and chunks (book_id, chunk_index)",
        "warnings": warnings,
    }
    out_path = OUTPUT_DIR / f"{book_id}_stage2_validation.json"
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {out_path}")
    print(
        f"stored={n_stored} null={n_null} dup_indexes={n_dup} failed={n_failed} seconds={elapsed}"
    )
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Stage 2: embed Stage 1 chunks into pgvector.")
    p.add_argument(
        "--chunks",
        type=Path,
        default=OUTPUT_DIR / "thinkpython_stage1_chunks.json",
        help="Path to Stage 1 validated chunks JSON.",
    )
    p.add_argument("--model", default=E5_MODEL)
    p.add_argument("--batch-size", type=int, default=16)
    p.add_argument("--device", default="cpu", help="cpu | mps | cuda | auto")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    run(
        args.chunks.expanduser().resolve(),
        model_name=args.model,
        batch_size=args.batch_size,
        device=args.device,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
