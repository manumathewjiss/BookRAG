"""
Time Qwen3-Reranker-0.6B on a fixed sample: RRF top-20 vs full union.

Does not overwrite the original 90-question rerank files.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from bge_m3_sparse import reciprocal_rank_fusion
from evaluate_qwen3_reranker_0_6b_local import (
    MODEL_ID,
    Qwen3Reranker,
    choose_device,
    load_chunks,
    rss_bytes,
)
from simulate_qwen3_reranker_pool_cutoff import rrf_order

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "outputs"
CUTOFF = 20
BATCH_SIZE = 2
# Fixed before the timing run: mix of easy items and the two Gita cutoff-sensitive questions.
SAMPLE = [
    ("thinkpython", "tp2_001"),
    ("thinkpython", "tp2_030"),
    ("arthashastra", "arth_001"),
    ("arthashastra", "arth_017"),
    ("bhagavad_gita", "bg_010"),
    ("bhagavad_gita", "bg_025"),
]


def score_pool(reranker, question: str, chunk_ids: list[int], chunks: dict, scores_saved: dict) -> dict:
    texts = [chunks[cid]["text"] for cid in chunk_ids]
    t0 = time.perf_counter()
    scores = reranker.score_pairs(question, texts, BATCH_SIZE)
    elapsed = time.perf_counter() - t0
    by_id = {cid: float(s) for cid, s in zip(chunk_ids, scores)}
    live_top10 = sorted(chunk_ids, key=lambda cid: (-by_id[cid], cid))[:10]
    saved_top10 = sorted(chunk_ids, key=lambda cid: (-scores_saved[cid], cid))[:10]
    return {
        "n_passages": len(chunk_ids),
        "seconds": round(elapsed, 3),
        "live_top10": live_top10,
        "saved_score_sim_top10": saved_top10,
        "top10_agrees_with_saved_score_simulation": live_top10 == saved_top10,
    }


def main() -> int:
    device, dtype, reason = choose_device("mps")
    print(f"Loading {MODEL_ID} device={device} dtype={dtype} ({reason})")
    reranker = Qwen3Reranker(MODEL_ID, device=device, dtype=dtype)
    hybrid_cache = {}
    rerank_cache = {}
    chunk_cache = {}
    rows = []
    for book_id, qid in SAMPLE:
        if book_id not in hybrid_cache:
            hybrid_cache[book_id] = json.loads(
                (OUTPUT_DIR / f"{book_id}_bge_m3_hybrid_retrieval_results_30.json").read_text(encoding="utf-8")
            )
            rerank_cache[book_id] = json.loads(
                (OUTPUT_DIR / f"{book_id}_qwen3_reranker_0_6b_local_retrieval_results_30.json").read_text(
                    encoding="utf-8"
                )
            )
            chunk_cache[book_id] = load_chunks(OUTPUT_DIR / f"{book_id}_stage1_chunks.json")
        hq = next(q for q in hybrid_cache[book_id]["questions"] if q["id"] == qid)
        rr = next(q for q in rerank_cache[book_id]["questions"] if q["id"] == qid)
        dense_ids = [int(h["chunk_index"]) for h in hq["dense_candidates"]]
        sparse_ids = [int(h["chunk_index"]) for h in hq["sparse_candidates"]]
        order = rrf_order(dense_ids, sparse_ids)
        saved = {int(c["chunk_index"]): float(c["rerank_score"]) for c in rr["candidates"]}
        cutoff_ids = order[:CUTOFF]
        print(f"Scoring {qid} cutoff={len(cutoff_ids)} full={len(order)}")
        cutoff = score_pool(reranker, hq["question"], cutoff_ids, chunk_cache[book_id], saved)
        full = score_pool(reranker, hq["question"], order, chunk_cache[book_id], saved)
        rows.append(
            {
                "id": qid,
                "book_id": book_id,
                "question": hq["question"],
                "n_union": len(order),
                "cutoff": CUTOFF,
                "cutoff_run": cutoff,
                "full_run": full,
                "seconds_per_passage_cutoff": round(cutoff["seconds"] / max(len(cutoff_ids), 1), 4),
                "seconds_per_passage_full": round(full["seconds"] / max(len(order), 1), 4),
            }
        )
        print(
            f"  {qid} cutoff {cutoff['seconds']:.2f}s full {full['seconds']:.2f}s "
            f"agree_cut={cutoff['top10_agrees_with_saved_score_simulation']} "
            f"agree_full={full['top10_agrees_with_saved_score_simulation']}"
        )

    cutoff_times = [r["cutoff_run"]["seconds"] for r in rows]
    full_times = [r["full_run"]["seconds"] for r in rows]

    def stats(xs: list[float]) -> dict:
        s = sorted(xs)
        return {
            "n": len(s),
            "mean": round(sum(s) / len(s), 3),
            "median": round(s[len(s) // 2], 3),
            "min": round(s[0], 3),
            "max": round(s[-1], 3),
        }

    payload = {
        "experiment": "qwen3_reranker_0_6b_local_pool_cutoff_timing",
        "model": MODEL_ID,
        "device": device,
        "dtype": str(dtype).replace("torch.", ""),
        "batch_size": BATCH_SIZE,
        "cutoff": CUTOFF,
        "sample_question_ids": [f"{b}:{q}" for b, q in SAMPLE],
        "sample_selection_rule": "two Think Python, two Arthashastra, plus Gita bg_010 and bg_025",
        "cutoff_seconds": stats(cutoff_times),
        "full_union_seconds": stats(full_times),
        "slowest_cutoff": max(rows, key=lambda r: r["cutoff_run"]["seconds"])["id"],
        "slowest_full": max(rows, key=lambda r: r["full_run"]["seconds"])["id"],
        "all_cutoff_top10_agreed_with_simulation": all(
            r["cutoff_run"]["top10_agrees_with_saved_score_simulation"] for r in rows
        ),
        "all_full_top10_agreed_with_simulation": all(
            r["full_run"]["top10_agrees_with_saved_score_simulation"] for r in rows
        ),
        "peak_rss_gib": round(rss_bytes() / (1024**3), 3),
        "questions": rows,
    }
    out = OUTPUT_DIR / "qwen3_reranker_0_6b_local_pool_cutoff_timing.json"
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {out}")
    print("cutoff", payload["cutoff_seconds"])
    print("full", payload["full_union_seconds"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
