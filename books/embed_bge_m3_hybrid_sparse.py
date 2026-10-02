"""
Store BGE-M3 sparse/lexical weights for existing Stage 1 chunks.

Does not re-chunk, does not overwrite E5 or BGE-M3 dense vectors,
and does not compute ColBERT or BM25.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

from bge_m3_sparse import BGE_MODEL, BgeM3SparseEncoder
from db import (
    apply_schema,
    bge_m3_embedding_row_count,
    bge_m3_hybrid_sparse_row_count,
    chunk_count_for_book,
    connect,
    embedding_row_count,
    upsert_bge_m3_hybrid_sparse_weights,
)
from embed_bge_m3_dense import load_stage1_chunks, model_revision

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "outputs"


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


def run_book(
    chunks_path: Path,
    *,
    encoder: BgeM3SparseEncoder,
    model_name: str,
    revision: str | None,
    batch_size: int,
) -> dict:
    payload = load_stage1_chunks(chunks_path)
    book_id = payload["book_id"]
    records = payload["chunks"]
    n_received = len(records)
    stage1_indexes = [int(r["chunk_index"]) for r in records]
    if stage1_indexes != list(range(n_received)) and sorted(stage1_indexes) != stage1_indexes:
        # still require unique indexes matching later DB rows
        pass
    if len(set(stage1_indexes)) != n_received:
        raise RuntimeError(f"Duplicate chunk_index values in {chunks_path}")

    texts = [r["text"] for r in records]
    t0 = time.perf_counter()
    print(f"Encoding {n_received} {book_id} chunks with {model_name} sparse lexical weights...")
    weights_list = encoder.encode_lexical_weights(texts, batch_size=batch_size)
    encode_seconds = time.perf_counter() - t0
    if len(weights_list) != n_received:
        raise RuntimeError(f"Sparse encode count {len(weights_list)} != {n_received}")
    empty = sum(1 for w in weights_list if not w)
    n_nonzero_mean = float(sum(len(w) for w in weights_list) / n_received)

    conn = connect()
    try:
        apply_schema(conn)
        n_e5_before = embedding_row_count(conn, book_id)
        n_dense_before = bge_m3_embedding_row_count(conn, book_id)
        rows = [
            {
                "book_id": book_id,
                "chunk_index": int(rec["chunk_index"]),
                "lexical_weights": weights,
                "n_nonzero": len(weights),
                "model_name": model_name,
            }
            for rec, weights in zip(records, weights_list)
        ]
        upsert_bge_m3_hybrid_sparse_weights(conn, rows)
        n_sparse = bge_m3_hybrid_sparse_row_count(conn, book_id)
        n_e5_after = embedding_row_count(conn, book_id)
        n_dense_after = bge_m3_embedding_row_count(conn, book_id)
        n_chunks = chunk_count_for_book(conn, book_id)
        stored_indexes = {int(r["chunk_index"]) for r in rows}
        stage1_set = set(stage1_indexes)
    finally:
        conn.close()

    if stored_indexes != stage1_set:
        raise RuntimeError(f"Sparse chunk_index set does not match Stage 1 for {book_id}")
    if n_e5_after != n_e5_before:
        raise RuntimeError(f"E5 embedding count changed for {book_id}: {n_e5_before} → {n_e5_after}")
    if n_dense_after != n_dense_before:
        raise RuntimeError(
            f"BGE-M3 dense count changed for {book_id}: {n_dense_before} → {n_dense_after}"
        )
    if n_sparse != n_received or n_sparse != n_chunks:
        raise RuntimeError(
            f"Sparse row count mismatch for {book_id}: sparse={n_sparse} received={n_received} chunks={n_chunks}"
        )

    report = {
        "stage": "bge_m3_hybrid_sparse_embed",
        "embedding_model": model_name,
        "model_revision": revision,
        "input_format": "raw chunk_text (BGE-M3 sparse docs: no passage:/query: prefixes)",
        "sparse_formula": "ReLU(sparse_linear(last_hidden_state)); max weight per token id; drop cls/eos/pad/unk",
        "modes_used": ["sparse"],
        "modes_not_used": ["colbert", "bm25", "rerank", "new_dense_model"],
        "dense_vectors": "reused from chunk_embeddings_bge_m3; not rewritten",
        "storage_table": "chunk_sparse_weights_bge_m3_hybrid",
        "max_length": encoder.max_length,
        "batch_size": batch_size,
        "device": encoder.device,
        "chunks_artifact": str(chunks_path),
        "chunks_sha256": sha256_file(chunks_path),
        "book_id": book_id,
        "total_chunks_received": n_received,
        "total_sparse_rows": n_sparse,
        "empty_sparse_vectors": empty,
        "mean_nonzero_tokens": n_nonzero_mean,
        "e5_embedding_row_count_unchanged": n_e5_after,
        "bge_m3_dense_row_count_unchanged": n_dense_after,
        "git_head": git_head(),
        "encode_seconds": round(encode_seconds, 3),
        "warnings": [] if empty == 0 else [f"{empty} chunks have empty lexical weights"],
    }
    out_path = OUTPUT_DIR / f"{book_id}_bge_m3_hybrid_sparse_validation.json"
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {out_path} sparse={n_sparse} seconds={encode_seconds:.1f}")
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Encode Stage 1 chunks with BGE-M3 sparse weights.")
    p.add_argument("--chunks", type=Path, action="append", required=True)
    p.add_argument("--model", default=BGE_MODEL)
    p.add_argument("--batch-size", type=int, default=4)
    p.add_argument("--device", default="cpu")
    p.add_argument("--max-length", type=int, default=512)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    revision = model_revision(args.model)
    print(f"Loading {args.model} sparse head revision={revision} device={args.device}")
    encoder = BgeM3SparseEncoder(args.model, device=args.device, max_length=args.max_length)
    for path in args.chunks:
        run_book(
            path.expanduser().resolve(),
            encoder=encoder,
            model_name=args.model,
            revision=revision,
            batch_size=args.batch_size,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
