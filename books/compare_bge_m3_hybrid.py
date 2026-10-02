"""
Compare E5, BGE-M3 dense-only, dense pool-30 top-10, and BGE-M3 hybrid RRF.

Does not re-run retrieval or modify gold labels / previous result files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "outputs"

GITA_REMAINING = ["bg_003", "bg_004", "bg_010", "bg_015", "bg_029"]
THINKPYTHON_CALLBACK = "tp2_030"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rank_key(rank: int | None) -> int:
    return 11 if rank is None else rank


def load_questions(path: Path) -> dict[str, dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {q["id"]: q for q in payload["questions"]}


def metrics_from_summary(path: Path) -> dict:
    s = json.loads(path.read_text(encoding="utf-8"))
    return {
        "hit@1": s["recall_hit@1"],
        "hit@5": s["recall_hit@5"],
        "hit@10": s["recall_hit@10"],
        "mrr@10": s["mrr@10"],
        "n_misses_top10": s.get("n_misses_top10"),
    }


def compare_book(book_id: str) -> dict:
    e5_sum = OUTPUT_DIR / f"{book_id}_stage3_retrieval_summary_30.json"
    dense_sum = OUTPUT_DIR / f"{book_id}_bge_m3_dense_retrieval_summary_30.json"
    hybrid_sum = OUTPUT_DIR / f"{book_id}_bge_m3_hybrid_retrieval_summary_30.json"
    e5_res = OUTPUT_DIR / f"{book_id}_stage3_retrieval_results_30.json"
    dense_res = OUTPUT_DIR / f"{book_id}_bge_m3_dense_retrieval_results_30.json"
    hybrid_res = OUTPUT_DIR / f"{book_id}_bge_m3_hybrid_retrieval_results_30.json"
    pool_res = OUTPUT_DIR / f"{book_id}_bge_m3_hybrid_dense_pool30_results_30.json"

    e5q = load_questions(e5_res)
    denseq = load_questions(dense_res)
    hybridq = load_questions(hybrid_res)
    poolq = load_questions(pool_res)
    hybrid_summary = json.loads(hybrid_sum.read_text(encoding="utf-8"))

    improved = worsened = unchanged = 0
    new_misses = []
    recovered = []
    per_question = []
    for qid in sorted(denseq):
        old = denseq[qid]["first_gold_rank"]
        new = hybridq[qid]["first_gold_rank"]
        pool_rank = poolq[qid]["first_gold_rank"]
        if rank_key(new) < rank_key(old):
            delta = "improved"
            improved += 1
        elif rank_key(new) > rank_key(old):
            delta = "worsened"
            worsened += 1
        else:
            delta = "unchanged"
            unchanged += 1
        if (old is None or old > 10) and new is not None and new <= 10:
            recovered.append(qid)
        if old is not None and old <= 10 and (new is None or new > 10):
            new_misses.append(qid)
        hq = hybridq[qid]
        per_question.append(
            {
                "id": qid,
                "question": denseq[qid]["question"],
                "gold_chunk_indexes": denseq[qid]["gold_chunk_indexes"],
                "e5_first_gold_rank": e5q[qid]["first_gold_rank"],
                "dense_first_gold_rank": old,
                "dense_pool30_top10_first_gold_rank": pool_rank,
                "sparse_top10_first_gold_rank": hq.get("sparse_top10_first_gold_rank"),
                "hybrid_first_gold_rank": new,
                "delta_dense_to_hybrid": delta,
                "hybrid_top10": [
                    {
                        "chunk_index": h["chunk_index"],
                        "dense_rank": h.get("dense_rank"),
                        "sparse_rank": h.get("sparse_rank"),
                        "rrf_score": h.get("rrf_score"),
                    }
                    for h in hq["retrieved"][:10]
                ],
            }
        )

    focus = {}
    if book_id == "bhagavad_gita":
        for qid in GITA_REMAINING:
            focus[qid] = {
                "e5": e5q[qid]["first_gold_rank"],
                "dense": denseq[qid]["first_gold_rank"],
                "dense_pool30_top10": poolq[qid]["first_gold_rank"],
                "sparse_top10": hybridq[qid].get("sparse_top10_first_gold_rank"),
                "hybrid": hybridq[qid]["first_gold_rank"],
                "recovered": hybridq[qid]["first_gold_rank"] is not None
                and hybridq[qid]["first_gold_rank"] <= 10,
            }
    if book_id == "thinkpython":
        qid = THINKPYTHON_CALLBACK
        focus[qid] = {
            "e5": e5q[qid]["first_gold_rank"],
            "dense": denseq[qid]["first_gold_rank"],
            "dense_pool30_top10": poolq[qid]["first_gold_rank"],
            "sparse_top10": hybridq[qid].get("sparse_top10_first_gold_rank"),
            "hybrid": hybridq[qid]["first_gold_rank"],
            "recovered": hybridq[qid]["first_gold_rank"] is not None
            and hybridq[qid]["first_gold_rank"] <= 10,
        }

    return {
        "book_id": book_id,
        "protected_file_sha256_16": {
            "e5_results": sha256_file(e5_res)[:16],
            "dense_results": sha256_file(dense_res)[:16],
        },
        "e5": metrics_from_summary(e5_sum),
        "bge_m3_dense": metrics_from_summary(dense_sum),
        "bge_m3_dense_pool30_top10": hybrid_summary["dense_pool30_top10"],
        "bge_m3_sparse_top10": hybrid_summary["sparse_top10"],
        "bge_m3_hybrid": metrics_from_summary(hybrid_sum),
        "n_improved_dense_to_hybrid": improved,
        "n_worsened_dense_to_hybrid": worsened,
        "n_unchanged_dense_to_hybrid": unchanged,
        "recovered_from_dense_miss": recovered,
        "new_misses_vs_dense": new_misses,
        "focus_questions": focus,
        "hybrid_settings": hybrid_summary["fusion"],
        "model_revision": hybrid_summary.get("model_revision"),
        "eval_sha256": hybrid_summary.get("eval_sha256"),
        "chunks_sha256": hybrid_summary.get("chunks_sha256"),
        "questions": per_question,
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, default=OUTPUT_DIR / "bge_m3_hybrid_vs_dense_comparison.json")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    payload = {
        "experiment": "bge_m3_dense_plus_sparse_rrf_k60",
        "books": [compare_book(b) for b in ("thinkpython", "arthashastra", "bhagavad_gita")],
    }
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {args.out}")
    for book in payload["books"]:
        h = book["bge_m3_hybrid"]
        d = book["bge_m3_dense"]
        print(
            f"{book['book_id']}: dense {d['hit@1']:.3f}/{d['hit@5']:.3f}/{d['hit@10']:.3f} "
            f"hybrid {h['hit@1']:.3f}/{h['hit@5']:.3f}/{h['hit@10']:.3f} "
            f"imp={book['n_improved_dense_to_hybrid']} worse={book['n_worsened_dense_to_hybrid']} "
            f"new_misses={book['new_misses_vs_dense']} recovered={book['recovered_from_dense_miss']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
