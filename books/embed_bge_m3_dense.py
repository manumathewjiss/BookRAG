"""
Embed existing Stage 1 chunks with BGE-M3 dense vectors only.

Does not re-chunk PDFs, does not touch E5 chunks.embedding,
does not use sparse or ColBERT modes, and does not use E5 prefixes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

from db import (
    apply_schema,
    bge_m3_embedding_row_count,
    chunk_count_for_book,
    connect,
    embedding_row_count,
    upsert_bge_m3_embeddings,
)

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "outputs"
BGE_MODEL = "BAAI/bge-m3"
EXPECTED_DIM = 1024
NORM_ATOL = 1e-3
# Official BGE-M3 examples encode raw sentences with no passage:/query: prefix.
INPUT_PREFIX = ""


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_head() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT.parent,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return None


def load_stage1_chunks(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("artifact") != "validated_chunks":
        raise ValueError(f"{path} is not a Stage 1 validated_chunks artifact.")
    chunks = payload.get("chunks")
    if not isinstance(chunks, list) or not chunks:
        raise ValueError(f"{path} contains no chunks.")
    return payload


def model_revision(model_name: str) -> str | None:
    try:
        from huggingface_hub import model_info

        return model_info(model_name).sha
    except Exception:
        return None


def load_bge_m3(model_name: str, device: str):
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(model_name, device=device)
    model.eval()
    return model


def embed_texts(model, texts: list[str], *, batch_size: int, device: str) -> np.ndarray:
    import torch

    with torch.inference_mode():
        embeddings = model.encode(
            texts,
            batch_size=batch_size,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=True,
            device=device,
        )
    return np.asarray(embeddings, dtype=np.float32)


def validate_embeddings(embeddings: np.ndarray, n_chunks: int) -> dict:
    if embeddings.ndim != 2:
        raise RuntimeError(f"Expected 2D embedding matrix, got shape {embeddings.shape}")
    n, dim = embeddings.shape
    if n != n_chunks:
        raise RuntimeError(f"Embedded {n} vectors but received {n_chunks} chunks.")
    if dim != EXPECTED_DIM:
        raise RuntimeError(f"BGE-M3 dense dim {dim} != {EXPECTED_DIM}")
    if not np.isfinite(embeddings).all():
        raise RuntimeError("BGE-M3 embeddings contain NaN or inf.")
    norms = np.linalg.norm(embeddings, axis=1)
    if not np.allclose(norms, 1.0, atol=NORM_ATOL):
        raise RuntimeError(
            f"BGE-M3 vectors are not unit-normalized: min={float(norms.min())} max={float(norms.max())}"
        )
    return {
        "n_embeddings": int(n),
        "embedding_dimension": int(dim),
        "minimum_vector_norm": float(norms.min()),
        "average_vector_norm": float(norms.mean()),
        "maximum_vector_norm": float(norms.max()),
        "normalized_vector_check": "pass",
    }


def run_book(
    chunks_path: Path,
    *,
    model,
    model_name: str,
    revision: str | None,
    batch_size: int,
    device: str,
) -> dict:
    payload = load_stage1_chunks(chunks_path)
    book_id = payload["book_id"]
    records = payload["chunks"]
    n_received = len(records)
    texts = [r["text"] for r in records]
    t0 = time.perf_counter()
    print(f"Embedding {n_received} {book_id} chunks with {model_name} dense (no E5 prefixes)...")
    embeddings = embed_texts(model, texts, batch_size=batch_size, device=device)
    emb_stats = validate_embeddings(embeddings, n_received)
    embed_seconds = time.perf_counter() - t0

    conn = connect()
    try:
        apply_schema(conn)
        n_e5_before = embedding_row_count(conn, book_id)
        rows = [
            {
                "book_id": book_id,
                "chunk_index": int(rec["chunk_index"]),
                "embedding": vec.tolist(),
                "model_name": model_name,
            }
            for rec, vec in zip(records, embeddings)
        ]
        upsert_bge_m3_embeddings(conn, rows)
        n_bge = bge_m3_embedding_row_count(conn, book_id)
        n_e5_after = embedding_row_count(conn, book_id)
        n_chunks = chunk_count_for_book(conn, book_id)
    finally:
        conn.close()

    if n_e5_after != n_e5_before:
        raise RuntimeError(f"E5 embedding count changed for {book_id}: {n_e5_before} → {n_e5_after}")
    if n_bge != n_received or n_bge != n_chunks:
        raise RuntimeError(
            f"BGE-M3 row count mismatch for {book_id}: bge={n_bge} received={n_received} chunks={n_chunks}"
        )

    report = {
        "stage": "bge_m3_dense_embed",
        "embedding_model": model_name,
        "model_revision": revision,
        "input_prefix": INPUT_PREFIX,
        "input_format": "raw chunk_text (BGE-M3 dense docs do not require passage:/query: prefixes)",
        "modes_used": ["dense"],
        "modes_not_used": ["sparse", "colbert", "bm25", "rerank"],
        "device": device,
        "batch_size": batch_size,
        "normalization": "L2 (SentenceTransformer normalize_embeddings=True)",
        "embedding_dimension": EXPECTED_DIM,
        "chunks_artifact": str(chunks_path),
        "chunks_sha256": sha256_file(chunks_path),
        "book_id": book_id,
        "total_chunks_received": n_received,
        "total_bge_m3_embeddings": n_bge,
        "e5_embedding_row_count_unchanged": n_e5_after,
        "storage_table": "chunk_embeddings_bge_m3",
        "e5_storage_column": "chunks.embedding",
        "git_head": git_head(),
        "embed_seconds": round(embed_seconds, 3),
        **emb_stats,
        "warnings": [],
    }
    out_path = OUTPUT_DIR / f"{book_id}_bge_m3_dense_stage2_validation.json"
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {out_path} stored={n_bge} e5_unchanged={n_e5_after} seconds={embed_seconds:.1f}")
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Embed Stage 1 chunks with BGE-M3 dense only.")
    p.add_argument("--chunks", type=Path, action="append", required=True)
    p.add_argument("--model", default=BGE_MODEL)
    p.add_argument("--batch-size", type=int, default=8)
    p.add_argument("--device", default="cpu")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    revision = model_revision(args.model)
    print(f"Loading {args.model} revision={revision} device={args.device}")
    model = load_bge_m3(args.model, args.device)
    for path in args.chunks:
        run_book(
            path.expanduser().resolve(),
            model=model,
            model_name=args.model,
            revision=revision,
            batch_size=args.batch_size,
            device=args.device,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
