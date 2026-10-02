"""
Evaluate frozen questions with BGE-M3 dense + BGE-M3 sparse RRF hybrid.

Reuses stored dense vectors. Writes new bge_m3_hybrid files only.
Does not modify E5 or dense-only result files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

from bge_m3_sparse import (
    BGE_MODEL,
    BgeM3SparseEncoder,
    build_sparse_index,
    reciprocal_rank_fusion,
    search_sparse,
)
from db import (
    apply_schema,
    bge_m3_embedding_row_count,
    bge_m3_hybrid_sparse_row_count,
    connect,
    embedding_row_count,
    load_bge_m3_hybrid_sparse_corpus,
    search_chunks_bge_m3,
)
from embed_bge_m3_dense import load_bge_m3, model_revision
from evaluate_bge_m3_dense import embed_query
from evaluate_retrieval_stage3 import (
    first_gold_rank,
    hit_at,
    load_eval_questions,
    mrr_from_rank,
    preview,
)

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "outputs"
CANDIDATE_K = 30
FINAL_K = 10
RRF_K = 60


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


def compact_hits(hits: list[dict], score_key: str) -> list[dict]:
    out = []
    for h in hits:
        item = {
            "rank": h["rank"],
            "chunk_index": h["chunk_index"],
            "page": h["page"],
            "text_preview": preview(h["text"]),
        }
        item[score_key] = h[score_key]
        out.append(item)
    return out


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="BGE-M3 dense+sparse RRF hybrid evaluation.")
    p.add_argument("--eval", type=Path, required=True)
    p.add_argument("--results", type=Path, required=True)
    p.add_argument("--summary", type=Path, required=True)
    p.add_argument("--dense-pool-results", type=Path, required=True)
    p.add_argument("--book-id", required=True)
    p.add_argument("--chunks", type=Path, required=True)
    p.add_argument("--device", default="cpu")
    p.add_argument("--candidate-k", type=int, default=CANDIDATE_K)
    p.add_argument("--final-k", type=int, default=FINAL_K)
    p.add_argument("--rrf-k", type=int, default=RRF_K)
    p.add_argument("--batch-size", type=int, default=4)
    return p.parse_args(argv)


def summarize_ranks(ranks: list[int | None], *, final_k: int) -> dict:
    n = len(ranks)
    return {
        "n_questions": n,
        "recall_hit@1": sum(hit_at(r, 1) for r in ranks) / n if n else 0.0,
        "recall_hit@5": sum(hit_at(r, 5) for r in ranks) / n if n else 0.0,
        "recall_hit@10": sum(hit_at(r, 10) for r in ranks) / n if n else 0.0,
        "mrr@10": sum(mrr_from_rank(r, 10) for r in ranks) / n if n else 0.0,
        "n_misses_top10": sum(1 for r in ranks if r is None or r > final_k),
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    questions = load_eval_questions(args.eval)
    revision = model_revision(BGE_MODEL)

    conn = connect()
    apply_schema(conn)
    n_e5_before = embedding_row_count(conn, args.book_id)
    n_dense_before = bge_m3_embedding_row_count(conn, args.book_id)
    n_sparse = bge_m3_hybrid_sparse_row_count(conn, args.book_id)
    corpus = load_bge_m3_hybrid_sparse_corpus(conn, args.book_id)
    if n_sparse != n_dense_before:
        raise RuntimeError(
            f"{args.book_id}: sparse rows {n_sparse} != dense rows {n_dense_before}"
        )
    stage1 = json.loads(args.chunks.read_text(encoding="utf-8"))
    stage1_ids = {int(c["chunk_index"]) for c in stage1["chunks"]}
    sparse_ids = {int(c["chunk_index"]) for c in corpus}
    if sparse_ids != stage1_ids:
        missing = sorted(stage1_ids - sparse_ids)
        extra = sorted(sparse_ids - stage1_ids)
        raise RuntimeError(f"{args.book_id} sparse IDs != Stage 1 missing={missing[:8]} extra={extra[:8]}")

    sparse_index = build_sparse_index(corpus)
    by_id = {int(c["chunk_index"]): c for c in corpus}

    print(f"Loading dense encoder {BGE_MODEL} for queries...")
    dense_model = load_bge_m3(BGE_MODEL, args.device)
    print("Loading sparse encoder for queries...")
    sparse_encoder = BgeM3SparseEncoder(BGE_MODEL, device=args.device, max_length=512)

    warnings: list[str] = []
    hybrid_rows: list[dict] = []
    dense_pool_rows: list[dict] = []
    hybrid_ranks: list[int | None] = []
    dense_pool_ranks: list[int | None] = []
    sparse_only_ranks: list[int | None] = []

    t0 = time.perf_counter()
    dense_query_s = sparse_query_s = dense_search_s = sparse_search_s = fuse_s = 0.0
    try:
        for item in questions:
            q = item["question"]
            book_id = item.get("book_id") or args.book_id
            if book_id != args.book_id:
                warnings.append(f"{item.get('id')}: question book_id {book_id} != {args.book_id}")
            gold = set(int(i) for i in item["gold_chunk_indexes"])

            tq = time.perf_counter()
            qvec, qstats = embed_query(dense_model, q, device=args.device)
            dense_query_s += time.perf_counter() - tq

            tq = time.perf_counter()
            q_sparse = sparse_encoder.encode_lexical_weights([q], batch_size=1)[0]
            sparse_query_s += time.perf_counter() - tq

            ts = time.perf_counter()
            dense_hits = search_chunks_bge_m3(
                conn,
                book_id=args.book_id,
                query_embedding=qvec.tolist(),
                top_k=args.candidate_k,
            )
            dense_search_s += time.perf_counter() - ts
            if any(h["book_id"] != args.book_id for h in dense_hits):
                raise RuntimeError("Dense search returned a foreign book_id.")

            ts = time.perf_counter()
            sparse_hits = search_sparse(
                query_weights=q_sparse,
                corpus=corpus,
                index=sparse_index,
                top_k=args.candidate_k,
            )
            sparse_search_s += time.perf_counter() - ts
            if any(h["book_id"] != args.book_id for h in sparse_hits):
                raise RuntimeError("Sparse search returned a foreign book_id.")

            tf = time.perf_counter()
            dense_ids = [h["chunk_index"] for h in dense_hits]
            sparse_ids_rank = [h["chunk_index"] for h in sparse_hits]
            fused = reciprocal_rank_fusion(
                [dense_ids, sparse_ids_rank],
                rrf_k=args.rrf_k,
                top_k=args.final_k,
            )
            fuse_s += time.perf_counter() - tf

            hybrid_hits = []
            for item_f in fused:
                row = by_id[item_f["chunk_index"]]
                hybrid_hits.append(
                    {
                        **item_f,
                        "page": row["page"],
                        "text": row["text"],
                        "book_id": args.book_id,
                    }
                )

            dense_top10 = dense_hits[: args.final_k]
            hybrid_rank = first_gold_rank([h["chunk_index"] for h in hybrid_hits], gold)
            dense_pool_rank = first_gold_rank([h["chunk_index"] for h in dense_top10], gold)
            sparse_rank = first_gold_rank(sparse_ids_rank[: args.final_k], gold)
            hybrid_ranks.append(hybrid_rank)
            dense_pool_ranks.append(dense_pool_rank)
            sparse_only_ranks.append(sparse_rank)

            common = {
                "id": item["id"],
                "question": q,
                "book_id": args.book_id,
                "gold_chunk_indexes": sorted(gold),
                "gold_pages": item.get("gold_pages"),
            }
            hybrid_rows.append(
                {
                    **common,
                    "query_embedding_dimension": qstats["dimension"],
                    "query_embedding_norm": qstats["norm"],
                    "query_sparse_nnz": len(q_sparse),
                    "dense_candidates": compact_hits(dense_hits, "similarity"),
                    "sparse_candidates": compact_hits(sparse_hits, "sparse_score"),
                    "retrieved": [
                        {
                            "rank": h["rank"],
                            "chunk_index": h["chunk_index"],
                            "page": h["page"],
                            "rrf_score": h["rrf_score"],
                            "dense_rank": h["dense_rank"],
                            "sparse_rank": h["sparse_rank"],
                            "text_preview": preview(h["text"]),
                        }
                        for h in hybrid_hits
                    ],
                    "first_gold_rank": hybrid_rank,
                    "dense_pool30_top10_first_gold_rank": dense_pool_rank,
                    "sparse_top10_first_gold_rank": sparse_rank,
                    "hit_at_1": hit_at(hybrid_rank, 1),
                    "hit_at_5": hit_at(hybrid_rank, 5),
                    "hit_at_10": hit_at(hybrid_rank, 10),
                    "reciprocal_rank": mrr_from_rank(hybrid_rank, 10),
                }
            )
            dense_pool_rows.append(
                {
                    **common,
                    "candidate_pool": args.candidate_k,
                    "retrieved": compact_hits(dense_top10, "similarity"),
                    "first_gold_rank": dense_pool_rank,
                    "hit_at_1": hit_at(dense_pool_rank, 1),
                    "hit_at_5": hit_at(dense_pool_rank, 5),
                    "hit_at_10": hit_at(dense_pool_rank, 10),
                    "reciprocal_rank": mrr_from_rank(dense_pool_rank, 10),
                }
            )
        n_e5_after = embedding_row_count(conn, args.book_id)
        n_dense_after = bge_m3_embedding_row_count(conn, args.book_id)
        if n_e5_after != n_e5_before:
            warnings.append(f"E5 embedding count changed: {n_e5_before} → {n_e5_after}")
        if n_dense_after != n_dense_before:
            warnings.append(f"Dense BGE count changed: {n_dense_before} → {n_dense_after}")
    finally:
        conn.close()

    elapsed = time.perf_counter() - t0
    hybrid_metrics = summarize_ranks(hybrid_ranks, final_k=args.final_k)
    dense_pool_metrics = summarize_ranks(dense_pool_ranks, final_k=args.final_k)
    sparse_metrics = summarize_ranks(sparse_only_ranks, final_k=args.final_k)

    payload = {
        "book_id": args.book_id,
        "embedding_family": "bge_m3_hybrid",
        "fusion": "reciprocal_rank_fusion",
        "rrf_k": args.rrf_k,
        "candidate_k": args.candidate_k,
        "final_k": args.final_k,
        "eval_file": str(args.eval),
        "eval_sha256": sha256_file(args.eval),
        "chunks_sha256": sha256_file(args.chunks),
        "n_questions": len(questions),
        "questions": hybrid_rows,
    }
    args.results.parent.mkdir(parents=True, exist_ok=True)
    args.results.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    dense_pool_payload = {
        "book_id": args.book_id,
        "embedding_family": "bge_m3_dense_pool30_top10",
        "note": "Exact dense search over the full book; top-10 of a 30-candidate pool. Original dense-only files were not rewritten.",
        "eval_file": str(args.eval),
        "eval_sha256": sha256_file(args.eval),
        "chunks_sha256": sha256_file(args.chunks),
        "n_questions": len(questions),
        "candidate_k": args.candidate_k,
        "final_k": args.final_k,
        "questions": dense_pool_rows,
    }
    args.dense_pool_results.write_text(
        json.dumps(dense_pool_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    summary = {
        "embedding_model": BGE_MODEL,
        "model_revision": revision,
        "embedding_family": "bge_m3_hybrid",
        "input_format": "raw question text; dense from SentenceTransformer; sparse from BGE-M3 sparse_linear",
        "fusion": {
            "method": "reciprocal_rank_fusion",
            "rrf_k": args.rrf_k,
            "formula": "1/(rrf_k + rank) summed over dense and sparse lists",
            "candidate_k_per_retriever": args.candidate_k,
            "final_k": args.final_k,
        },
        "modes_used": ["dense", "sparse", "rrf"],
        "modes_not_used": ["colbert", "bm25", "rerank", "llm"],
        "book_filter": args.book_id,
        "n_e5_embeddings": n_e5_after,
        "n_bge_m3_dense_embeddings": n_dense_after,
        "n_bge_m3_hybrid_sparse_rows": n_sparse,
        "hybrid": hybrid_metrics,
        "dense_pool30_top10": dense_pool_metrics,
        "sparse_top10": sparse_metrics,
        "processing_time_seconds": round(elapsed, 3),
        "dense_query_embed_seconds": round(dense_query_s, 3),
        "sparse_query_embed_seconds": round(sparse_query_s, 3),
        "dense_search_seconds": round(dense_search_s, 3),
        "sparse_search_seconds": round(sparse_search_s, 3),
        "fusion_seconds": round(fuse_s, 3),
        "eval_sha256": sha256_file(args.eval),
        "chunks_sha256": sha256_file(args.chunks),
        "git_head": git_head(),
        "results_file": str(args.results),
        "dense_pool_results_file": str(args.dense_pool_results),
        "warnings": warnings,
        "errors": [],
        "generation": "not implemented",
    }
    # flatten hybrid metrics to recall_hit@k for compare script compatibility
    summary.update(
        {
            "recall_hit@1": hybrid_metrics["recall_hit@1"],
            "recall_hit@5": hybrid_metrics["recall_hit@5"],
            "recall_hit@10": hybrid_metrics["recall_hit@10"],
            "mrr@10": hybrid_metrics["mrr@10"],
            "n_misses_top10": hybrid_metrics["n_misses_top10"],
            "n_evaluation_questions": hybrid_metrics["n_questions"],
        }
    )
    args.summary.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{args.book_id} BGE-M3 hybrid RRF k={args.rrf_k}")
    print(
        f"Hybrid Hit@1/5/10 {hybrid_metrics['recall_hit@1']:.4f}/"
        f"{hybrid_metrics['recall_hit@5']:.4f}/{hybrid_metrics['recall_hit@10']:.4f} "
        f"MRR {hybrid_metrics['mrr@10']:.4f} misses={hybrid_metrics['n_misses_top10']}"
    )
    print(
        f"Dense pool30 top10 Hit@1/5/10 {dense_pool_metrics['recall_hit@1']:.4f}/"
        f"{dense_pool_metrics['recall_hit@5']:.4f}/{dense_pool_metrics['recall_hit@10']:.4f}"
    )
    print(f"Wrote {args.results}")
    print(f"Wrote {args.summary}")
    print(f"Wrote {args.dense_pool_results}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
