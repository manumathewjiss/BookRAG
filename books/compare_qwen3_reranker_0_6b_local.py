"""
Compare local Qwen3-Reranker-0.6B top-10 with saved BGE-M3 hybrid RRF.

Does not re-run models or overwrite prior files.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "outputs"
BOOKS = ("thinkpython", "arthashastra", "bhagavad_gita")
FOCUS = ("bg_010", "bg_025", "tp2_030")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rank_key(rank: int | None) -> int:
    return 11 if rank is None else rank


def load_q(path: Path) -> dict[str, dict]:
    return {q["id"]: q for q in json.loads(path.read_text(encoding="utf-8"))["questions"]}


def metrics_counts(ranks: list[int | None]) -> dict:
    n = len(ranks)
    n1 = sum(1 for r in ranks if r is not None and r <= 1)
    n5 = sum(1 for r in ranks if r is not None and r <= 5)
    n10 = sum(1 for r in ranks if r is not None and r <= 10)
    mrr = sum((1.0 / r) if r is not None and r <= 10 else 0.0 for r in ranks) / n if n else 0.0
    return {"n_hit@1": n1, "n_hit@5": n5, "n_hit@10": n10, "mrr@10": mrr, "n_misses_top10": n - n10}


def main() -> int:
    books = []
    for book_id in BOOKS:
        hybrid_path = OUTPUT_DIR / f"{book_id}_bge_m3_hybrid_retrieval_results_30.json"
        rerank_path = OUTPUT_DIR / f"{book_id}_qwen3_reranker_0_6b_local_retrieval_results_30.json"
        summary_path = OUTPUT_DIR / f"{book_id}_qwen3_reranker_0_6b_local_retrieval_summary_30.json"
        hq = load_q(hybrid_path)
        rq = load_q(rerank_path)
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        improved = worsened = unchanged = 0
        improved_ids = []
        worsened_ids = []
        gold_missing = []
        dir_top10 = []
        rows = []
        h_ranks = []
        r_ranks = []
        for qid in sorted(hq):
            old = hq[qid]["first_gold_rank"]
            new = rq[qid]["first_gold_rank"]
            h_ranks.append(old)
            r_ranks.append(new)
            if rank_key(new) < rank_key(old):
                improved += 1
                improved_ids.append(qid)
                delta = "improved"
            elif rank_key(new) > rank_key(old):
                worsened += 1
                worsened_ids.append(qid)
                delta = "worsened"
            else:
                unchanged += 1
                delta = "unchanged"
            gold_in = rq[qid].get("gold_in_candidate_list") or []
            if not gold_in:
                gold_missing.append(qid)
            n_dir = sum(1 for h in rq[qid]["retrieved"] if h.get("is_address_directory"))
            if n_dir:
                dir_top10.append({"id": qid, "n_directory_in_top10": n_dir})
            rows.append(
                {
                    "id": qid,
                    "question": hq[qid]["question"],
                    "gold_chunk_indexes": hq[qid]["gold_chunk_indexes"],
                    "hybrid_first_gold_rank": old,
                    "rerank_first_gold_rank": new,
                    "gold_in_candidate_list": gold_in,
                    "delta": delta,
                    "rerank_top10": [
                        {
                            "rank": h["rank"],
                            "chunk_index": h["chunk_index"],
                            "rerank_score": h.get("rerank_score"),
                            "dense_rank": h.get("dense_rank"),
                            "sparse_rank": h.get("sparse_rank"),
                            "is_address_directory": h.get("is_address_directory"),
                            "text_preview": h.get("text_preview"),
                        }
                        for h in rq[qid]["retrieved"]
                    ],
                    "hybrid_top10": [
                        {"rank": h["rank"], "chunk_index": h["chunk_index"]}
                        for h in hq[qid]["retrieved"][:10]
                    ],
                }
            )
        focus = {}
        for qid in FOCUS:
            row = next((x for x in rows if x["id"] == qid), None)
            if row:
                focus[qid] = row
        books.append(
            {
                "book_id": book_id,
                "protected_sha256_16": {
                    "hybrid": sha256_file(hybrid_path)[:16],
                },
                "hybrid": metrics_counts(h_ranks),
                "qwen3_reranker_0_6b_local": {
                    **metrics_counts(r_ranks),
                    "device": summary.get("device"),
                    "dtype": summary.get("dtype"),
                    "model_revision": summary.get("model_revision"),
                    "processing_time_seconds": summary.get("processing_time_seconds"),
                    "peak_rss_gib": summary.get("peak_rss_gib"),
                    "n_pairs_scored": summary.get("n_pairs_scored"),
                },
                "n_improved": improved,
                "n_worsened": worsened,
                "n_unchanged": unchanged,
                "improved_ids": improved_ids,
                "worsened_ids": worsened_ids,
                "gold_missing_from_candidates": gold_missing,
                "questions_with_directory_in_rerank_top10": dir_top10,
                "focus_questions": focus,
                "questions": rows,
            }
        )
    out = OUTPUT_DIR / "qwen3_reranker_0_6b_local_vs_hybrid_comparison.json"
    payload = {
        "experiment": "qwen3_reranker_0_6b_local_on_bge_m3_hybrid_candidates",
        "books": books,
    }
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {out}")
    for b in books:
        r = b["qwen3_reranker_0_6b_local"]
        h = b["hybrid"]
        print(
            f"{b['book_id']}: hybrid {h['n_hit@1']}/{h['n_hit@5']}/{h['n_hit@10']} "
            f"rerank {r['n_hit@1']}/{r['n_hit@5']}/{r['n_hit@10']} "
            f"imp={b['improved_ids']} worse={b['worsened_ids']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
