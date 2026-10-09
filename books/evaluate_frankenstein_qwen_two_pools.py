"""
Frankenstein new-book test: Qwen on hybrid top 20 vs hybrid-10-then-interleave 20.

Does not overwrite earlier books' files or change production defaults.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from compare_qwen_pool_hybrid_reserved_offline import pool_hybrid_then_interleave
from compare_qwen_pool_selection_offline import ranked_ids, sha256_file
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
)
from evaluate_retrieval_stage3 import first_gold_rank, hit_at, mrr_from_rank

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "outputs"
BOOK_ID = "frankenstein_1532610843_print"
POOL_K = 20
FINAL_K = 10


def rank_key(rank: int | None) -> int:
    return 11 if rank is None else rank


def write_method_payload(
    *,
    method_name: str,
    label: str,
    rows: list[dict],
    ranks: list[int | None],
    n_gold_in: int,
    extra: dict,
) -> dict:
    mets = metrics_from_ranks(ranks)
    return {
        "book_id": BOOK_ID,
        "method": method_name,
        "label": label,
        "reranker_model": MODEL_ID,
        "pool_k": POOL_K,
        "final_k": FINAL_K,
        "n_gold_reached_qwen": n_gold_in,
        "questions": rows,
        **mets,
        **extra,
    }


def main() -> int:
    hybrid_path = OUTPUT_DIR / "frankenstein_bge_m3_hybrid_retrieval_results.json"
    chunks_path = OUTPUT_DIR / "frankenstein_1532610843_print_stage1_chunks.json"
    eval_path = OUTPUT_DIR / "frankenstein_retrieval_eval_frozen_30.json"
    freeze_path = OUTPUT_DIR / "frankenstein_retrieval_eval_frozen_30.sha256.json"
    hybrid_results_path = OUTPUT_DIR / "frankenstein_qwen3_reranker_hybrid_pool20_results.json"
    hybrid_summary_path = OUTPUT_DIR / "frankenstein_qwen3_reranker_hybrid_pool20_summary.json"
    cand_results_path = OUTPUT_DIR / "frankenstein_qwen3_reranker_hybrid10_then_interleave_results.json"
    cand_summary_path = OUTPUT_DIR / "frankenstein_qwen3_reranker_hybrid10_then_interleave_summary.json"
    compare_path = OUTPUT_DIR / "frankenstein_hybrid20_vs_hybrid10_interleave_comparison.json"

    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    eval_sha = sha256_file(eval_path)
    if eval_sha != freeze["sha256"]:
        raise RuntimeError("Frozen eval file hash changed after freeze; aborting.")

    free = disk_free_gb(Path.home())
    print(f"Disk free: {free:.1f} GiB")
    if free < 1.0:
        print("Refusing: under 1 GiB free.")
        return 2

    hybrid = json.loads(hybrid_path.read_text(encoding="utf-8"))
    chunks = load_chunks(chunks_path)
    questions = hybrid["questions"]

    device, dtype, reason = choose_device("mps")
    print(f"Device={device} dtype={dtype} ({reason})")
    reranker = Qwen3Reranker(MODEL_ID, device=device, dtype=dtype)

    saved_scores: dict[str, dict[int, float]] = {}

    def score_missing(qid: str, question: str, pool: list[int]) -> tuple[dict[int, float], int, int, float]:
        have = saved_scores.setdefault(qid, {})
        missing = [cid for cid in pool if cid not in have]
        reused = len(pool) - len(missing)
        t0 = time.perf_counter()
        if missing:
            texts = [chunks[cid]["text"] for cid in missing]
            scores = reranker.score_pairs(question, texts, batch_size=2)
            for cid, s in zip(missing, scores):
                have[cid] = float(s)
        elapsed = time.perf_counter() - t0
        return have, reused, len(missing), elapsed

    def rank_pool(qid: str, question: str, gold: set[int], pool: list[int], scores: dict[int, float]) -> dict:
        ranked = sorted(pool, key=lambda cid: (-scores[cid], cid))
        rank = first_gold_rank(ranked[:FINAL_K], gold)
        gold_ids = [cid for cid in pool if cid in gold]
        cands = [
            {
                "chunk_index": cid,
                "page": chunks[cid].get("page"),
                "rerank_score": scores[cid],
                "rerank_rank": i,
                "text_preview": preview(chunks[cid]["text"]),
            }
            for i, cid in enumerate(ranked, start=1)
        ]
        return {
            "id": qid,
            "question": question,
            "gold_chunk_indexes": sorted(gold),
            "gold_in_pool": gold_ids,
            "gold_reached_qwen": bool(gold_ids),
            "n_candidates": len(pool),
            "candidates": cands,
            "retrieved": [
                {
                    "rank": c["rerank_rank"],
                    "chunk_index": c["chunk_index"],
                    "page": c["page"],
                    "rerank_score": c["rerank_score"],
                    "text_preview": c["text_preview"],
                }
                for c in cands[:FINAL_K]
            ],
            "first_gold_rank": rank,
            "hit_at_1": hit_at(rank, 1),
            "hit_at_5": hit_at(rank, 5),
            "hit_at_10": hit_at(rank, 10),
            "reciprocal_rank": mrr_from_rank(rank, 10),
        }

    hybrid_rows = []
    hybrid_ranks: list[int | None] = []
    n_gold_h = 0
    n_reused_h = n_new_h = 0
    score_s_h = 0.0
    t_h0 = time.perf_counter()
    for hq in questions:
        qid = hq["id"]
        gold = set(int(i) for i in hq["gold_chunk_indexes"])
        pool = [int(h["chunk_index"]) for h in sorted(hq["retrieved"], key=lambda x: int(x["rank"]))][:POOL_K]
        scores, reused, new, elapsed = score_missing(qid, hq["question"], pool)
        n_reused_h += reused
        n_new_h += new
        score_s_h += elapsed
        row = rank_pool(qid, hq["question"], gold, pool, scores)
        row["n_scores_reused"] = reused
        row["n_scores_new"] = new
        row["score_seconds"] = round(elapsed, 3)
        hybrid_rows.append(row)
        hybrid_ranks.append(row["first_gold_rank"])
        if row["gold_reached_qwen"]:
            n_gold_h += 1
        print(f"HYB {qid} gold_in={row['gold_reached_qwen']} rank={row['first_gold_rank']} new={new} {elapsed:.1f}s")
    hybrid_wall = time.perf_counter() - t_h0

    cand_rows = []
    cand_ranks: list[int | None] = []
    n_gold_c = 0
    n_reused_c = n_new_c = 0
    score_s_c = 0.0
    t_c0 = time.perf_counter()
    for hq in questions:
        qid = hq["id"]
        gold = set(int(i) for i in hq["gold_chunk_indexes"])
        dense_ids = ranked_ids(hq["dense_candidates"])
        sparse_ids = ranked_ids(hq["sparse_candidates"])
        pool = pool_hybrid_then_interleave(dense_ids, sparse_ids, n_hybrid=10)
        scores, reused, new, elapsed = score_missing(qid, hq["question"], pool)
        n_reused_c += reused
        n_new_c += new
        score_s_c += elapsed
        row = rank_pool(qid, hq["question"], gold, pool, scores)
        row["n_scores_reused"] = reused
        row["n_scores_new"] = new
        row["score_seconds"] = round(elapsed, 3)
        cand_rows.append(row)
        cand_ranks.append(row["first_gold_rank"])
        if row["gold_reached_qwen"]:
            n_gold_c += 1
        print(f"H10 {qid} gold_in={row['gold_reached_qwen']} rank={row['first_gold_rank']} new={new} {elapsed:.1f}s")
    cand_wall = time.perf_counter() - t_c0

    nq = len(questions)
    hybrid_payload = write_method_payload(
        method_name="hybrid_rrf_top20",
        label="First 20 passages from BGE-M3 hybrid RRF",
        rows=hybrid_rows,
        ranks=hybrid_ranks,
        n_gold_in=n_gold_h,
        extra={
            "device": device,
            "dtype": str(dtype).replace("torch.", ""),
            "batch_size": 2,
            "eval_sha256": eval_sha,
            "n_scores_reused": n_reused_h,
            "n_scores_new": n_new_h,
            "qwen_score_seconds": round(score_s_h, 3),
            "qwen_wall_seconds": round(hybrid_wall, 3),
            "mean_qwen_score_seconds_per_question": round(score_s_h / nq, 3),
        },
    )
    hybrid_results_path.write_text(json.dumps(hybrid_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    hybrid_summary = {
        "method": "hybrid_rrf_top20",
        "book_id": BOOK_ID,
        "n_gold_reached_qwen": n_gold_h,
        "qwen_score_seconds": round(score_s_h, 3),
        "mean_qwen_score_seconds_per_question": round(score_s_h / nq, 3),
        "peak_rss_gib": round(rss_bytes() / (1024**3), 3),
        "git_head": git_head(),
        "eval_sha256": eval_sha,
        **metrics_from_ranks(hybrid_ranks),
    }
    hybrid_summary_path.write_text(json.dumps(hybrid_summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    cand_payload = write_method_payload(
        method_name="hybrid10_then_interleave",
        label="First 10 hybrid RRF passages, then alternate meaning and word ranks to 20 unique",
        rows=cand_rows,
        ranks=cand_ranks,
        n_gold_in=n_gold_c,
        extra={
            "device": device,
            "dtype": str(dtype).replace("torch.", ""),
            "batch_size": 2,
            "eval_sha256": eval_sha,
            "n_scores_reused": n_reused_c,
            "n_scores_new": n_new_c,
            "qwen_score_seconds": round(score_s_c, 3),
            "qwen_wall_seconds": round(cand_wall, 3),
            "mean_qwen_score_seconds_per_question": round(score_s_c / nq, 3),
        },
    )
    cand_results_path.write_text(json.dumps(cand_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    cand_summary = {
        "method": "hybrid10_then_interleave",
        "book_id": BOOK_ID,
        "n_gold_reached_qwen": n_gold_c,
        "qwen_score_seconds": round(score_s_c, 3),
        "mean_qwen_score_seconds_per_question": round(score_s_c / nq, 3),
        "peak_rss_gib": round(rss_bytes() / (1024**3), 3),
        "git_head": git_head(),
        "eval_sha256": eval_sha,
        **metrics_from_ranks(cand_ranks),
    }
    cand_summary_path.write_text(json.dumps(cand_summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    hy = {r["id"]: r for r in hybrid_rows}
    improved, worsened, gained, lost = [], [], [], []
    for r in cand_rows:
        old, new = hy[r["id"]], r
        if new["gold_reached_qwen"] and not old["gold_reached_qwen"]:
            gained.append(r["id"])
        if old["gold_reached_qwen"] and not new["gold_reached_qwen"]:
            lost.append(r["id"])
        if rank_key(new["first_gold_rank"]) < rank_key(old["first_gold_rank"]):
            improved.append({"id": r["id"], "hybrid20": old["first_gold_rank"], "hybrid10_interleave": new["first_gold_rank"]})
        elif rank_key(new["first_gold_rank"]) > rank_key(old["first_gold_rank"]):
            worsened.append({"id": r["id"], "hybrid20": old["first_gold_rank"], "hybrid10_interleave": new["first_gold_rank"]})

    compare = {
        "book_id": BOOK_ID,
        "eval_sha256": eval_sha,
        "eval_unchanged_since_freeze": True,
        "production_pipeline_changed": False,
        "hybrid_rrf_top20": {
            "n_gold_reached_qwen": n_gold_h,
            **{k: hybrid_summary[k] for k in ("n_hit@1", "n_hit@5", "n_hit@10", "mrr@10")},
            "mean_qwen_score_seconds_per_question": hybrid_summary["mean_qwen_score_seconds_per_question"],
        },
        "hybrid10_then_interleave": {
            "n_gold_reached_qwen": n_gold_c,
            **{k: cand_summary[k] for k in ("n_hit@1", "n_hit@5", "n_hit@10", "mrr@10")},
            "mean_qwen_score_seconds_per_question": cand_summary["mean_qwen_score_seconds_per_question"],
        },
        "pool_gained_ids": gained,
        "pool_lost_ids": lost,
        "rerank_improved": improved,
        "rerank_worsened": worsened,
        "device_reason": reason,
    }
    compare_path.write_text(json.dumps(compare, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("HYBRID20", n_gold_h, hybrid_summary["n_hit@1"], hybrid_summary["n_hit@5"], hybrid_summary["n_hit@10"], f"{score_s_h/nq:.2f}s/q")
    print("H10+INT ", n_gold_c, cand_summary["n_hit@1"], cand_summary["n_hit@5"], cand_summary["n_hit@10"], f"{score_s_c/nq:.2f}s/q")
    print("gained", gained, "lost", lost, "better", [x["id"] for x in improved], "worse", [x["id"] for x in worsened])
    print(f"Wrote {compare_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
