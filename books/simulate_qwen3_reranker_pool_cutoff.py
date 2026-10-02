"""
Simulate Qwen reranker pool cutoffs from saved hybrid lists and saved scores.

Does not load the reranker. Does not overwrite prior result files.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from bge_m3_sparse import reciprocal_rank_fusion
from evaluate_retrieval_stage3 import first_gold_rank, hit_at, mrr_from_rank

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "outputs"
BOOKS = ("thinkpython", "arthashastra", "bhagavad_gita")
CUTOFFS = (10, 20, 30, 40)
RRF_K = 60
FINAL_K = 10
FOCUS = ("bg_010", "bg_025")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rank_key(rank: int | None) -> int:
    return 11 if rank is None else rank


def metrics(ranks: list[int | None]) -> dict:
    n = len(ranks)
    n1 = sum(1 for r in ranks if hit_at(r, 1))
    n5 = sum(1 for r in ranks if hit_at(r, 5))
    n10 = sum(1 for r in ranks if hit_at(r, 10))
    return {
        "n_questions": n,
        "n_gold_available": None,
        "n_hit@1": n1,
        "n_hit@5": n5,
        "n_hit@10": n10,
        "mrr@10": sum(mrr_from_rank(r, 10) for r in ranks) / n if n else 0.0,
    }


def rrf_order(dense_ids: list[int], sparse_ids: list[int]) -> list[int]:
    n = len(set(dense_ids) | set(sparse_ids))
    fused = reciprocal_rank_fusion([dense_ids, sparse_ids], rrf_k=RRF_K, top_k=n)
    return [int(x["chunk_index"]) for x in fused]


def simulate_cutoff(order: list[int], scores: dict[int, float], gold: set[int], k: int | None) -> dict:
    pool = order if k is None else order[:k]
    gold_in = sorted(gold & set(pool))
    missing_scores = [cid for cid in pool if cid not in scores]
    ranked = sorted(pool, key=lambda cid: (-scores.get(cid, float("-inf")), cid))
    top10 = ranked[:FINAL_K]
    return {
        "n_pool": len(pool),
        "gold_available": bool(gold_in),
        "gold_in_pool": gold_in,
        "gold_rrf_position": next((i for i, cid in enumerate(order, start=1) if cid in gold), None),
        "first_gold_rank": first_gold_rank(top10, gold) if gold_in else None,
        "top10": top10,
        "missing_saved_scores": missing_scores,
    }


def process_book(book_id: str) -> dict:
    hybrid_path = OUTPUT_DIR / f"{book_id}_bge_m3_hybrid_retrieval_results_30.json"
    rerank_path = OUTPUT_DIR / f"{book_id}_qwen3_reranker_0_6b_local_retrieval_results_30.json"
    hybrid = json.loads(hybrid_path.read_text(encoding="utf-8"))
    rerank = json.loads(rerank_path.read_text(encoding="utf-8"))
    rq = {q["id"]: q for q in rerank["questions"]}
    reproduce_ok = True
    mismatches = []
    questions = []
    cutoff_ranks: dict[str, list[int | None]] = {f"k{k}": [] for k in CUTOFFS}
    cutoff_ranks["full"] = []
    cutoff_avail: dict[str, int] = {f"k{k}": 0 for k in CUTOFFS}
    cutoff_avail["full"] = 0

    for hq in hybrid["questions"]:
        qid = hq["id"]
        rr = rq[qid]
        gold = set(int(i) for i in hq["gold_chunk_indexes"])
        dense_ids = [int(h["chunk_index"]) for h in hq["dense_candidates"]]
        sparse_ids = [int(h["chunk_index"]) for h in hq["sparse_candidates"]]
        order = rrf_order(dense_ids, sparse_ids)
        saved_top10 = [int(h["chunk_index"]) for h in hq["retrieved"][:10]]
        rebuilt_top10 = order[:10]
        if saved_top10 != rebuilt_top10:
            reproduce_ok = False
            mismatches.append({"id": qid, "saved": saved_top10, "rebuilt": rebuilt_top10})
        scores = {int(c["chunk_index"]): float(c["rerank_score"]) for c in rr["candidates"]}
        full = simulate_cutoff(order, scores, gold, None)
        sims = {"full": full}
        for k in CUTOFFS:
            sims[f"k{k}"] = simulate_cutoff(order, scores, gold, k)
        saved_full_rank = rr["first_gold_rank"]
        if full["first_gold_rank"] != saved_full_rank:
            reproduce_ok = False
            mismatches.append(
                {
                    "id": qid,
                    "type": "full_rerank_mismatch",
                    "saved_rerank": saved_full_rank,
                    "simulated_full": full["first_gold_rank"],
                }
            )
        for key, sim in sims.items():
            cutoff_ranks[key].append(sim["first_gold_rank"])
            if sim["gold_available"]:
                cutoff_avail[key] += 1
        questions.append(
            {
                "id": qid,
                "question": hq["question"],
                "gold_chunk_indexes": sorted(gold),
                "n_union": len(order),
                "hybrid_first_gold_rank": hq["first_gold_rank"],
                "saved_rerank_first_gold_rank": saved_full_rank,
                "gold_rrf_position": full["gold_rrf_position"],
                "cutoffs": {key: {k: v for k, v in sim.items() if k != "top10"} | {"top10": sim["top10"]} for key, sim in sims.items()},
            }
        )

    method_metrics = {}
    vs_full = {}
    full_by_id = {q["id"]: q["cutoffs"]["full"]["first_gold_rank"] for q in questions}
    for key in [f"k{k}" for k in CUTOFFS] + ["full"]:
        ranks = cutoff_ranks[key]
        m = metrics(ranks)
        m["n_gold_available"] = cutoff_avail[key]
        method_metrics[key] = m
        if key == "full":
            continue
        improved = []
        worsened = []
        excluded = []
        for q in questions:
            old = full_by_id[q["id"]]
            new = q["cutoffs"][key]["first_gold_rank"]
            if not q["cutoffs"][key]["gold_available"]:
                excluded.append(q["id"])
            if rank_key(new) < rank_key(old):
                improved.append(q["id"])
            elif rank_key(new) > rank_key(old):
                worsened.append(q["id"])
        vs_full[key] = {
            "n_improved": len(improved),
            "n_worsened": len(worsened),
            "improved_ids": improved,
            "worsened_ids": worsened,
            "gold_excluded_ids": excluded,
        }

    focus = {}
    for qid in FOCUS:
        q = next((x for x in questions if x["id"] == qid), None)
        if q:
            focus[qid] = {
                "gold_chunk_indexes": q["gold_chunk_indexes"],
                "gold_rrf_position": q["gold_rrf_position"],
                "n_union": q["n_union"],
                "ranks": {key: q["cutoffs"][key]["first_gold_rank"] for key in method_metrics},
                "gold_available": {key: q["cutoffs"][key]["gold_available"] for key in method_metrics},
            }

    return {
        "book_id": book_id,
        "hybrid_sha256": sha256_file(hybrid_path),
        "rerank_sha256": sha256_file(rerank_path),
        "rrf_top10_matches_saved_hybrid": reproduce_ok,
        "mismatches": mismatches,
        "metrics": method_metrics,
        "vs_full_rerank": vs_full,
        "focus_questions": focus,
        "questions": questions,
    }


def main() -> int:
    books = [process_book(b) for b in BOOKS]
    payload = {
        "experiment": "qwen3_reranker_0_6b_local_pool_cutoff_simulation",
        "note": (
            "Reranker scores come from the saved full-list run. "
            "A cutoff that excludes the gold chunk cannot recover it."
        ),
        "cutoffs": list(CUTOFFS) + ["full_union"],
        "rrf_k": RRF_K,
        "books": books,
    }
    out = OUTPUT_DIR / "qwen3_reranker_0_6b_local_pool_cutoff_simulation.json"
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {out}")
    for book in books:
        print(f"\n{book['book_id']} rrf_match={book['rrf_top10_matches_saved_hybrid']}")
        for key, m in book["metrics"].items():
            print(
                f"  {key}: gold_in={m['n_gold_available']}/30 "
                f"@1/5/10={m['n_hit@1']}/{m['n_hit@5']}/{m['n_hit@10']}"
            )
            if key in book["vs_full_rerank"]:
                d = book["vs_full_rerank"][key]
                print(
                    f"    vs full worse={d['worsened_ids']} excluded={d['gold_excluded_ids']}"
                )
        if book["focus_questions"]:
            print("  focus", book["focus_questions"])
    return 0 if all(b["rrf_top10_matches_saved_hybrid"] for b in books) else 1


if __name__ == "__main__":
    raise SystemExit(main())
