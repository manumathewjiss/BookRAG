"""
Stage 3 retrieval evaluation on the frozen Think Python question set.

Gold labels come from Stage 1 chunks and are frozen before search.
Does not generate answers, rerank, or re-embed passages.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from db import connect, embedding_row_count, search_chunks
from retrieve_stage3 import (
    E5_MODEL,
    EXPECTED_DIM,
    QUERY_PREFIX,
    embed_query,
    load_e5_encoder,
)

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "outputs"
EVAL_DEFAULT = OUTPUT_DIR / "thinkpython_retrieval_eval_frozen.json"
RESULTS_DEFAULT = OUTPUT_DIR / "thinkpython_stage3_retrieval_results.json"
SUMMARY_DEFAULT = OUTPUT_DIR / "thinkpython_stage3_retrieval_summary.json"
TOP_K = 10
PREVIEW_CHARS = 180


def load_eval_questions(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        questions = payload
    else:
        questions = payload["questions"]
    if not questions:
        raise RuntimeError(f"No questions in {path}")
    return questions


def first_gold_rank(retrieved_indexes: list[int], gold_indexes: set[int]) -> int | None:
    for i, idx in enumerate(retrieved_indexes, start=1):
        if idx in gold_indexes:
            return i
    return None


def hit_at(rank: int | None, k: int) -> bool:
    return rank is not None and rank <= k


def mrr_from_rank(rank: int | None, k: int = TOP_K) -> float:
    if rank is None or rank > k:
        return 0.0
    return 1.0 / rank


def preview(text: str, n: int = PREVIEW_CHARS) -> str:
    t = " ".join(text.split())
    return t if len(t) <= n else t[: n - 1] + "…"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Evaluate frozen retrieval questions (Stage 3).")
    p.add_argument("--eval", type=Path, default=EVAL_DEFAULT)
    p.add_argument("--results", type=Path, default=RESULTS_DEFAULT)
    p.add_argument("--summary", type=Path, default=SUMMARY_DEFAULT)
    p.add_argument("--top-k", type=int, default=TOP_K)
    p.add_argument("--device", default="cpu")
    p.add_argument("--book-id", default="thinkpython")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    questions = load_eval_questions(args.eval)
    model = load_e5_encoder(device=args.device)
    warnings: list[str] = []
    errors: list[str] = []
    results: list[dict] = []
    ranks: list[int | None] = []

    conn = connect()
    t0 = time.perf_counter()
    try:
        n_embeddings_before = embedding_row_count(conn, args.book_id)
        for item in questions:
            q = item["question"]
            book_id = item.get("book_id") or args.book_id
            gold = set(int(i) for i in item["gold_chunk_indexes"])
            try:
                qvec, qstats = embed_query(model, q, device=args.device)
                hits = search_chunks(
                    conn,
                    book_id=book_id,
                    query_embedding=qvec.tolist(),
                    top_k=args.top_k,
                )
            except Exception as exc:
                errors.append(f"{item.get('id')}: {exc}")
                ranks.append(None)
                results.append(
                    {
                        "id": item["id"],
                        "question": q,
                        "book_id": book_id,
                        "gold_chunk_indexes": sorted(gold),
                        "gold_pages": item.get("gold_pages"),
                        "retrieved": [],
                        "first_gold_rank": None,
                        "hit_at_1": False,
                        "hit_at_5": False,
                        "hit_at_10": False,
                        "reciprocal_rank": 0.0,
                        "error": str(exc),
                    }
                )
                continue

            retrieved_indexes = [h["chunk_index"] for h in hits]
            rank = first_gold_rank(retrieved_indexes, gold)
            ranks.append(rank)
            retrieved = []
            for h in hits:
                retrieved.append(
                    {
                        "rank": h["rank"],
                        "chunk_index": h["chunk_index"],
                        "page": h["page"],
                        "similarity": h["similarity"],
                        "text_preview": preview(h["text"]),
                    }
                )
            results.append(
                {
                    "id": item["id"],
                    "question": q,
                    "book_id": book_id,
                    "gold_chunk_indexes": sorted(gold),
                    "gold_pages": item.get("gold_pages"),
                    "query_embedding_dimension": qstats["dimension"],
                    "query_embedding_norm": qstats["norm"],
                    "retrieved": retrieved,
                    "first_gold_rank": rank,
                    "hit_at_1": hit_at(rank, 1),
                    "hit_at_5": hit_at(rank, 5),
                    "hit_at_10": hit_at(rank, 10),
                    "reciprocal_rank": mrr_from_rank(rank, args.top_k),
                }
            )
        n_embeddings_after = embedding_row_count(conn, args.book_id)
        if n_embeddings_after != n_embeddings_before:
            warnings.append(
                f"Embedding row count changed during eval: {n_embeddings_before} → {n_embeddings_after}"
            )
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
        "eval_file": str(args.eval),
        "n_questions": n,
        "top_k": args.top_k,
        "questions": results,
    }
    args.results.parent.mkdir(parents=True, exist_ok=True)
    args.results.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    summary = {
        "embedding_model": E5_MODEL,
        "query_prefix": QUERY_PREFIX,
        "embedding_dimension": EXPECTED_DIM,
        "normalization": "L2 (SentenceTransformer normalize_embeddings=True)",
        "similarity_method": "pgvector <#> negative inner product; reported similarity = -neg_ip (≈ cosine for unit vectors)",
        "search": "exact",
        "ann_index": "none (no HNSW/IVFFlat)",
        "book_filter": args.book_id,
        "n_evaluation_questions": n,
        "recall_hit@1": recall1,
        "recall_hit@5": recall5,
        "recall_hit@10": recall10,
        "mrr@10": mrr10,
        "n_misses_top10": n_miss,
        "processing_time_seconds": round(elapsed, 3),
        "n_embeddings_before": n_embeddings_before,
        "n_embeddings_after": n_embeddings_after,
        "results_file": str(args.results),
        "warnings": warnings,
        "errors": errors,
        "generation": "not implemented (Stage 3 ends at retrieval)",
    }
    args.summary.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"Questions: {n}")
    print(f"Recall/Hit@1:  {recall1:.4f}")
    print(f"Recall/Hit@5:  {recall5:.4f}")
    print(f"Recall/Hit@10: {recall10:.4f}")
    print(f"MRR@10:        {mrr10:.4f}")
    print(f"Misses@10:     {n_miss}")
    print(f"Time (s):      {elapsed:.3f}")
    print(f"Wrote {args.results}")
    print(f"Wrote {args.summary}")
    if errors:
        print("Errors:")
        for e in errors:
            print(f"  {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
