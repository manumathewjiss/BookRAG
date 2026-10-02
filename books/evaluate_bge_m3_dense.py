"""
Evaluate frozen Stage 3 questions using BGE-M3 dense retrieval only.

Reuses gold labels and Hit@K / MRR@10 definitions from evaluate_retrieval_stage3.py.
Does not search E5 vectors or change frozen question files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

from db import (
    apply_schema,
    bge_m3_embedding_row_count,
    connect,
    embedding_row_count,
    search_chunks_bge_m3,
)
from embed_bge_m3_dense import BGE_MODEL, EXPECTED_DIM, INPUT_PREFIX, load_bge_m3, model_revision
from evaluate_retrieval_stage3 import (
    TOP_K,
    first_gold_rank,
    hit_at,
    load_eval_questions,
    mrr_from_rank,
    preview,
)

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "outputs"
NORM_ATOL = 1e-3


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


def embed_query(model, question: str, *, device: str) -> tuple[np.ndarray, dict]:
    import os

    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    import torch

    with torch.inference_mode():
        vec = model.encode(
            [question],
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
            device=device,
        )
    vec = np.asarray(vec, dtype=np.float32)
    if vec.ndim != 2 or vec.shape[0] != 1:
        raise RuntimeError(f"Unexpected query embedding shape: {vec.shape}")
    dim = int(vec.shape[1])
    if dim != EXPECTED_DIM:
        raise RuntimeError(f"Query embedding dim {dim} != {EXPECTED_DIM}")
    if not np.isfinite(vec).all():
        raise RuntimeError("Query embedding contains NaN or inf.")
    norm = float(np.linalg.norm(vec[0]))
    if abs(norm - 1.0) > NORM_ATOL:
        raise RuntimeError(f"Query embedding is not unit-normalized: norm={norm}")
    stats = {
        "model": BGE_MODEL,
        "query_prefix": INPUT_PREFIX,
        "dimension": dim,
        "norm": norm,
        "normalized": True,
    }
    return vec[0], stats


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Evaluate frozen questions with BGE-M3 dense search.")
    p.add_argument("--eval", type=Path, required=True)
    p.add_argument("--results", type=Path, required=True)
    p.add_argument("--summary", type=Path, required=True)
    p.add_argument("--book-id", required=True)
    p.add_argument("--top-k", type=int, default=TOP_K)
    p.add_argument("--device", default="cpu")
    p.add_argument("--chunks", type=Path, required=True, help="Stage 1 chunks JSON (for hashing only).")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    questions = load_eval_questions(args.eval)
    revision = model_revision(BGE_MODEL)
    model = load_bge_m3(BGE_MODEL, args.device)
    warnings: list[str] = []
    errors: list[str] = []
    results: list[dict] = []
    ranks: list[int | None] = []

    conn = connect()
    apply_schema(conn)
    t0 = time.perf_counter()
    query_embed_seconds = 0.0
    search_seconds = 0.0
    try:
        n_e5 = embedding_row_count(conn, args.book_id)
        n_bge_before = bge_m3_embedding_row_count(conn, args.book_id)
        for item in questions:
            q = item["question"]
            book_id = item.get("book_id") or args.book_id
            if book_id != args.book_id:
                warnings.append(f"{item.get('id')}: question book_id {book_id} != {args.book_id}")
            gold = set(int(i) for i in item["gold_chunk_indexes"])
            tq = time.perf_counter()
            qvec, qstats = embed_query(model, q, device=args.device)
            query_embed_seconds += time.perf_counter() - tq
            ts = time.perf_counter()
            hits = search_chunks_bge_m3(
                conn,
                book_id=args.book_id,
                query_embedding=qvec.tolist(),
                top_k=args.top_k,
            )
            search_seconds += time.perf_counter() - ts
            if any(h["book_id"] != args.book_id for h in hits):
                raise RuntimeError("Search returned a foreign book_id.")
            retrieved_indexes = [h["chunk_index"] for h in hits]
            rank = first_gold_rank(retrieved_indexes, gold)
            ranks.append(rank)
            results.append(
                {
                    "id": item["id"],
                    "question": q,
                    "book_id": args.book_id,
                    "gold_chunk_indexes": sorted(gold),
                    "gold_pages": item.get("gold_pages"),
                    "query_embedding_dimension": qstats["dimension"],
                    "query_embedding_norm": qstats["norm"],
                    "retrieved": [
                        {
                            "rank": h["rank"],
                            "chunk_index": h["chunk_index"],
                            "page": h["page"],
                            "similarity": h["similarity"],
                            "text_preview": preview(h["text"]),
                        }
                        for h in hits
                    ],
                    "first_gold_rank": rank,
                    "hit_at_1": hit_at(rank, 1),
                    "hit_at_5": hit_at(rank, 5),
                    "hit_at_10": hit_at(rank, 10),
                    "reciprocal_rank": mrr_from_rank(rank, args.top_k),
                }
            )
        n_bge_after = bge_m3_embedding_row_count(conn, args.book_id)
        n_e5_after = embedding_row_count(conn, args.book_id)
        if n_e5_after != n_e5:
            warnings.append(f"E5 embedding count changed: {n_e5} → {n_e5_after}")
        if n_bge_after != n_bge_before:
            warnings.append(f"BGE-M3 row count changed during eval: {n_bge_before} → {n_bge_after}")
    finally:
        conn.close()

    elapsed = time.perf_counter() - t0
    n = len(ranks)
    n_miss = sum(1 for r in ranks if r is None)
    recall1 = sum(hit_at(r, 1) for r in ranks) / n if n else 0.0
    recall5 = sum(hit_at(r, 5) for r in ranks) / n if n else 0.0
    recall10 = sum(hit_at(r, 10) for r in ranks) / n if n else 0.0
    mrr10 = sum(mrr_from_rank(r, 10) for r in ranks) / n if n else 0.0

    payload = {
        "book_id": args.book_id,
        "embedding_family": "bge_m3_dense",
        "eval_file": str(args.eval),
        "eval_sha256": sha256_file(args.eval),
        "chunks_sha256": sha256_file(args.chunks),
        "n_questions": n,
        "top_k": args.top_k,
        "questions": results,
    }
    args.results.parent.mkdir(parents=True, exist_ok=True)
    args.results.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    summary = {
        "embedding_model": BGE_MODEL,
        "model_revision": revision,
        "embedding_family": "bge_m3_dense",
        "query_prefix": INPUT_PREFIX,
        "input_format": "raw question text (no E5 query: prefix)",
        "embedding_dimension": EXPECTED_DIM,
        "normalization": "L2 (SentenceTransformer normalize_embeddings=True)",
        "similarity_method": "pgvector <#> on chunk_embeddings_bge_m3 only",
        "search": "exact",
        "ann_index": "none",
        "book_filter": args.book_id,
        "n_evaluation_questions": n,
        "recall_hit@1": recall1,
        "recall_hit@5": recall5,
        "recall_hit@10": recall10,
        "mrr@10": mrr10,
        "n_misses_top10": n_miss,
        "processing_time_seconds": round(elapsed, 3),
        "query_embed_seconds": round(query_embed_seconds, 3),
        "search_seconds": round(search_seconds, 3),
        "n_e5_embeddings": n_e5_after,
        "n_bge_m3_embeddings": n_bge_after,
        "eval_sha256": sha256_file(args.eval),
        "chunks_sha256": sha256_file(args.chunks),
        "git_head": git_head(),
        "results_file": str(args.results),
        "warnings": warnings,
        "errors": errors,
        "generation": "not implemented",
    }
    args.summary.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{args.book_id} BGE-M3 dense")
    print(f"Questions: {n}")
    print(f"Recall/Hit@1:  {recall1:.4f}")
    print(f"Recall/Hit@5:  {recall5:.4f}")
    print(f"Recall/Hit@10: {recall10:.4f}")
    print(f"MRR@10:        {mrr10:.4f}")
    print(f"Misses@10:     {n_miss}")
    print(f"Query embed s: {query_embed_seconds:.3f}")
    print(f"Search s:      {search_seconds:.3f}")
    print(f"Wrote {args.results}")
    print(f"Wrote {args.summary}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
