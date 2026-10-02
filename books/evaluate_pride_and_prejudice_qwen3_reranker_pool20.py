"""
Pride and Prejudice transfer test: rerank the first 20 hybrid RRF passages.

Uses saved hybrid retrieved lists (not dense∪sparse union). Full Stage 1 text.
Does not change the production Qwen evaluator defaults.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from evaluate_qwen3_reranker_0_6b_local import (
    MODEL_ID,
    Qwen3Reranker,
    choose_device,
    disk_free_gb,
    git_head,
    load_chunks,
    metrics_from_ranks,
    preview,
    rss_bytes,
    sha256_file,
)
from evaluate_retrieval_stage3 import first_gold_rank, hit_at, mrr_from_rank
from huggingface_hub import model_info

POOL_K = 20
FINAL_K = 10


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Rerank first 20 hybrid passages with local Qwen3-Reranker-0.6B.")
    p.add_argument("--book-id", required=True)
    p.add_argument("--hybrid", type=Path, required=True)
    p.add_argument("--chunks", type=Path, required=True)
    p.add_argument("--eval", type=Path, required=True)
    p.add_argument("--results", type=Path, required=True)
    p.add_argument("--summary", type=Path, required=True)
    p.add_argument("--device", default="mps", choices=["auto", "mps", "cpu"])
    p.add_argument("--batch-size", type=int, default=2)
    p.add_argument("--pool-k", type=int, default=POOL_K)
    p.add_argument("--min-free-gb", type=float, default=3.0)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    free = disk_free_gb(Path.home())
    print(f"Disk free: {free:.1f} GiB")
    if free < args.min_free_gb:
        print(f"Refusing to download: only {free:.1f} GiB free (need {args.min_free_gb}).")
        return 2

    try:
        info = model_info(MODEL_ID)
        revision = info.sha
    except Exception as exc:
        revision = "local-cache"
        print(f"model_info unavailable ({exc}); using cached {MODEL_ID}")
    print(f"Model {MODEL_ID} revision={revision}")

    device, dtype, reason = choose_device(args.device)
    print(f"Device={device} dtype={dtype} ({reason})")
    reranker = Qwen3Reranker(MODEL_ID, device=device, dtype=dtype)

    hybrid = json.loads(args.hybrid.read_text(encoding="utf-8"))
    chunks = load_chunks(args.chunks)
    questions = hybrid["questions"]

    results = []
    ranks: list[int | None] = []
    n_gold_in_pool = 0
    t0 = time.perf_counter()
    score_seconds = 0.0
    n_pairs = 0
    per_question_seconds: list[float] = []
    for q in questions:
        gold = set(int(i) for i in q["gold_chunk_indexes"])
        retrieved = q.get("retrieved") or []
        pool = retrieved[: args.pool_k]
        if len(pool) < args.pool_k:
            print(f"WARNING {q['id']}: hybrid retrieved {len(pool)} < pool_k {args.pool_k}")
        cands = []
        for h in pool:
            cid = int(h["chunk_index"])
            if cid not in chunks:
                raise RuntimeError(f"chunk_index {cid} missing from Stage 1 file")
            cands.append(
                {
                    "chunk_index": cid,
                    "hybrid_rank": int(h["rank"]),
                    "page": chunks[cid].get("page"),
                    "text": chunks[cid]["text"],
                    "rrf_score": h.get("rrf_score"),
                    "dense_rank": h.get("dense_rank"),
                    "sparse_rank": h.get("sparse_rank"),
                }
            )
        gold_in_list = sorted(gold & {c["chunk_index"] for c in cands})
        if gold_in_list:
            n_gold_in_pool += 1
        n_pairs += len(cands)
        ts = time.perf_counter()
        scores = reranker.score_pairs(q["question"], [c["text"] for c in cands], args.batch_size)
        qsec = time.perf_counter() - ts
        score_seconds += qsec
        per_question_seconds.append(qsec)
        for cand, score in zip(cands, scores):
            cand["rerank_score"] = score
        ranked = sorted(cands, key=lambda c: (-c["rerank_score"], c["chunk_index"]))
        for i, cand in enumerate(ranked, start=1):
            cand["rerank_rank"] = i
        top10 = ranked[:FINAL_K]
        rank = first_gold_rank([c["chunk_index"] for c in top10], gold)
        ranks.append(rank)
        results.append(
            {
                "id": q["id"],
                "question": q["question"],
                "book_id": args.book_id,
                "gold_chunk_indexes": sorted(gold),
                "gold_in_hybrid_pool20": gold_in_list,
                "gold_reached_reranker_pool20": bool(gold_in_list),
                "n_candidates": len(cands),
                "score_seconds": round(qsec, 3),
                "candidates": [
                    {
                        "chunk_index": c["chunk_index"],
                        "page": c["page"],
                        "hybrid_rank": c["hybrid_rank"],
                        "dense_rank": c["dense_rank"],
                        "sparse_rank": c["sparse_rank"],
                        "rerank_score": c["rerank_score"],
                        "rerank_rank": c["rerank_rank"],
                        "text_preview": preview(c["text"]),
                    }
                    for c in ranked
                ],
                "retrieved": [
                    {
                        "rank": c["rerank_rank"],
                        "chunk_index": c["chunk_index"],
                        "page": c["page"],
                        "rerank_score": c["rerank_score"],
                        "hybrid_rank": c["hybrid_rank"],
                        "dense_rank": c["dense_rank"],
                        "sparse_rank": c["sparse_rank"],
                        "text_preview": preview(c["text"]),
                    }
                    for c in top10
                ],
                "first_gold_rank": rank,
                "hit_at_1": hit_at(rank, 1),
                "hit_at_5": hit_at(rank, 5),
                "hit_at_10": hit_at(rank, 10),
                "reciprocal_rank": mrr_from_rank(rank, 10),
            }
        )
        print(
            f"{q['id']} pool={len(cands)} gold_in_pool={bool(gold_in_list)} "
            f"rerank_gold_rank={rank} top1={top10[0]['chunk_index']} "
            f"score={top10[0]['rerank_score']:.4f} {qsec:.1f}s"
        )

    elapsed = time.perf_counter() - t0
    mets = metrics_from_ranks(ranks)
    n = len(questions)
    payload = {
        "book_id": args.book_id,
        "embedding_family": "qwen3_reranker_0_6b_local_hybrid_pool20",
        "reranker_model": MODEL_ID,
        "model_revision": revision,
        "device": device,
        "dtype": str(dtype).replace("torch.", ""),
        "batch_size": args.batch_size,
        "candidate_source": "first 20 passages of saved BGE-M3 hybrid RRF retrieved list",
        "pool_k": args.pool_k,
        "final_k": FINAL_K,
        "passage_text": "full Stage 1 chunk text",
        "eval_file": str(args.eval),
        "eval_sha256": sha256_file(args.eval),
        "chunks_sha256": sha256_file(args.chunks),
        "hybrid_sha256": sha256_file(args.hybrid),
        "n_questions": n,
        "n_gold_reached_pool20": n_gold_in_pool,
        "questions": results,
    }
    args.results.parent.mkdir(parents=True, exist_ok=True)
    args.results.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    mean_q = score_seconds / n if n else 0.0
    summary = {
        "reranker_model": MODEL_ID,
        "model_revision": revision,
        "embedding_family": "qwen3_reranker_0_6b_local_hybrid_pool20",
        "device": device,
        "device_reason": reason,
        "dtype": str(dtype).replace("torch.", ""),
        "batch_size": args.batch_size,
        "pool_k": args.pool_k,
        "book_filter": args.book_id,
        "n_pairs_scored": n_pairs,
        "n_gold_reached_pool20": n_gold_in_pool,
        "frac_gold_reached_pool20": n_gold_in_pool / n if n else 0.0,
        "processing_time_seconds": round(elapsed, 3),
        "score_seconds": round(score_seconds, 3),
        "mean_score_seconds_per_question": round(mean_q, 3),
        "peak_rss_bytes": rss_bytes(),
        "peak_rss_gib": round(rss_bytes() / (1024**3), 3),
        "git_head": git_head(),
        "eval_sha256": sha256_file(args.eval),
        "chunks_sha256": sha256_file(args.chunks),
        "hybrid_sha256": sha256_file(args.hybrid),
        "results_file": str(args.results),
        "gold_labels_given_to_model": False,
        "warnings": [],
        "errors": [],
        **mets,
    }
    args.summary.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{args.book_id} Qwen3-Reranker-0.6B pool{args.pool_k} {device}")
    print(f"Hit@1/5/10 {mets['n_hit@1']}/{mets['n_hit@5']}/{mets['n_hit@10']} MRR={mets['mrr@10']:.4f}")
    print(f"Gold in pool20 {n_gold_in_pool}/{n} time/q {mean_q:.1f}s")
    print(f"Wrote {args.results}")
    print(f"Wrote {args.summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
