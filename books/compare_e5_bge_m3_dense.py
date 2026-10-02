"""
Compare frozen 30-question E5 results with BGE-M3 dense results.

Does not re-run retrieval or modify gold labels.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "outputs"

GITA_E5_TOP10_MISSES = [
    "bg_003",
    "bg_004",
    "bg_010",
    "bg_015",
    "bg_020",
    "bg_022",
    "bg_024",
]


def rank_key(rank: int | None) -> int:
    return 11 if rank is None else rank


def load_results(path: Path) -> dict[str, dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {q["id"]: q for q in payload["questions"]}


def compare_book(*, book_id: str, e5_results: Path, e5_summary: Path, bge_results: Path, bge_summary: Path) -> dict:
    e5s = json.loads(e5_summary.read_text(encoding="utf-8"))
    bges = json.loads(bge_summary.read_text(encoding="utf-8"))
    e5q = load_results(e5_results)
    bgeq = load_results(bge_results)
    ids = sorted(set(e5q) | set(bgeq))
    improved = worsened = unchanged = 0
    per_question = []
    for qid in ids:
        er, br = e5q[qid], bgeq[qid]
        old, new = er["first_gold_rank"], br["first_gold_rank"]
        if rank_key(new) < rank_key(old):
            delta = "improved"
            improved += 1
        elif rank_key(new) > rank_key(old):
            delta = "worsened"
            worsened += 1
        else:
            delta = "unchanged"
            unchanged += 1
        per_question.append(
            {
                "id": qid,
                "question": er["question"],
                "gold_chunk_indexes": er["gold_chunk_indexes"],
                "e5_first_gold_rank": old,
                "bge_m3_first_gold_rank": new,
                "delta": delta,
                "e5_top5": [
                    {"chunk_index": h["chunk_index"], "page": h["page"], "similarity": h["similarity"]}
                    for h in er["retrieved"][:5]
                ],
                "bge_m3_top5": [
                    {"chunk_index": h["chunk_index"], "page": h["page"], "similarity": h["similarity"]}
                    for h in br["retrieved"][:5]
                ],
            }
        )
    gita_misses = []
    if book_id == "bhagavad_gita":
        for qid in GITA_E5_TOP10_MISSES:
            if qid in e5q and qid in bgeq:
                gita_misses.append(
                    {
                        "id": qid,
                        "question": e5q[qid]["question"],
                        "e5_rank": e5q[qid]["first_gold_rank"],
                        "bge_m3_rank": bgeq[qid]["first_gold_rank"],
                        "fixed_top10": e5q[qid]["first_gold_rank"] is None
                        and bgeq[qid]["first_gold_rank"] is not None,
                        "still_miss": bgeq[qid]["first_gold_rank"] is None,
                    }
                )
    return {
        "book_id": book_id,
        "n_questions": len(ids),
        "e5": {
            "hit@1": e5s["recall_hit@1"],
            "hit@5": e5s["recall_hit@5"],
            "hit@10": e5s["recall_hit@10"],
            "mrr@10": e5s["mrr@10"],
            "n_misses_top10": e5s["n_misses_top10"],
            "eval_seconds": e5s.get("processing_time_seconds"),
        },
        "bge_m3_dense": {
            "hit@1": bges["recall_hit@1"],
            "hit@5": bges["recall_hit@5"],
            "hit@10": bges["recall_hit@10"],
            "mrr@10": bges["mrr@10"],
            "n_misses_top10": bges["n_misses_top10"],
            "eval_seconds": bges.get("processing_time_seconds"),
            "query_embed_seconds": bges.get("query_embed_seconds"),
            "search_seconds": bges.get("search_seconds"),
            "model_revision": bges.get("model_revision"),
        },
        "n_improved": improved,
        "n_worsened": worsened,
        "n_unchanged": unchanged,
        "gita_e5_top10_misses": gita_misses,
        "questions": per_question,
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, default=OUTPUT_DIR / "bge_m3_dense_vs_e5_comparison.json")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    books = [
        (
            "thinkpython",
            OUTPUT_DIR / "thinkpython_stage3_retrieval_results_30.json",
            OUTPUT_DIR / "thinkpython_stage3_retrieval_summary_30.json",
            OUTPUT_DIR / "thinkpython_bge_m3_dense_retrieval_results_30.json",
            OUTPUT_DIR / "thinkpython_bge_m3_dense_retrieval_summary_30.json",
        ),
        (
            "arthashastra",
            OUTPUT_DIR / "arthashastra_stage3_retrieval_results_30.json",
            OUTPUT_DIR / "arthashastra_stage3_retrieval_summary_30.json",
            OUTPUT_DIR / "arthashastra_bge_m3_dense_retrieval_results_30.json",
            OUTPUT_DIR / "arthashastra_bge_m3_dense_retrieval_summary_30.json",
        ),
        (
            "bhagavad_gita",
            OUTPUT_DIR / "bhagavad_gita_stage3_retrieval_results_30.json",
            OUTPUT_DIR / "bhagavad_gita_stage3_retrieval_summary_30.json",
            OUTPUT_DIR / "bhagavad_gita_bge_m3_dense_retrieval_results_30.json",
            OUTPUT_DIR / "bhagavad_gita_bge_m3_dense_retrieval_summary_30.json",
        ),
    ]
    payload = {"experiment": "e5_vs_bge_m3_dense_same_chunks_same_30q", "books": []}
    for book_id, er, es, br, bs in books:
        payload["books"].append(
            compare_book(book_id=book_id, e5_results=er, e5_summary=es, bge_results=br, bge_summary=bs)
        )
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {args.out}")
    for book in payload["books"]:
        print(
            f"{book['book_id']}: E5 {book['e5']['hit@1']:.3f}/{book['e5']['hit@5']:.3f}/{book['e5']['hit@10']:.3f} "
            f"BGE {book['bge_m3_dense']['hit@1']:.3f}/{book['bge_m3_dense']['hit@5']:.3f}/{book['bge_m3_dense']['hit@10']:.3f} "
            f"imp={book['n_improved']} worse={book['n_worsened']} same={book['n_unchanged']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
