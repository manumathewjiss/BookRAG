"""
Offline comparison of 20-passage Qwen pool rules from saved search lists.

Does not search, embed, rerank, or overwrite baseline files.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from bge_m3_sparse import reciprocal_rank_fusion
from evaluate_retrieval_stage3 import first_gold_rank, hit_at, mrr_from_rank

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "outputs"
POOL_K = 20
RRF_K = 60
FOCUS_IDS = ("pp_003", "pp_021", "pp_028", "bg_010", "bg_025")
BOOKS = (
    {
        "book_id": "thinkpython",
        "hybrid": OUTPUT_DIR / "thinkpython_bge_m3_hybrid_retrieval_results_30.json",
        "qwen": OUTPUT_DIR / "thinkpython_qwen3_reranker_0_6b_local_retrieval_results_30.json",
        "eval": OUTPUT_DIR / "thinkpython_retrieval_eval_frozen_30.json",
    },
    {
        "book_id": "arthashastra",
        "hybrid": OUTPUT_DIR / "arthashastra_bge_m3_hybrid_retrieval_results_30.json",
        "qwen": OUTPUT_DIR / "arthashastra_qwen3_reranker_0_6b_local_retrieval_results_30.json",
        "eval": OUTPUT_DIR / "arthashastra_retrieval_eval_frozen_30.json",
    },
    {
        "book_id": "bhagavad_gita",
        "hybrid": OUTPUT_DIR / "bhagavad_gita_bge_m3_hybrid_retrieval_results_30.json",
        "qwen": OUTPUT_DIR / "bhagavad_gita_qwen3_reranker_0_6b_local_retrieval_results_30.json",
        "eval": OUTPUT_DIR / "bhagavad_gita_retrieval_eval_frozen_30.json",
    },
    {
        "book_id": "pride_and_prejudice",
        "hybrid": OUTPUT_DIR / "pride_and_prejudice_bge_m3_hybrid_retrieval_results.json",
        "qwen": OUTPUT_DIR / "pride_and_prejudice_qwen3_reranker_0_6b_pool20_results.json",
        "eval": OUTPUT_DIR / "pride_and_prejudice_retrieval_eval_frozen_30.json",
    },
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ranked_ids(hits: list[dict], limit: int | None = None) -> list[int]:
    ordered = sorted(hits, key=lambda h: int(h["rank"]))
    ids = [int(h["chunk_index"]) for h in ordered]
    if limit is not None:
        return ids[:limit]
    return ids


def rrf_top(dense_ids: list[int], sparse_ids: list[int], k: int) -> list[int]:
    n = len(set(dense_ids) | set(sparse_ids))
    fused = reciprocal_rank_fusion([dense_ids, sparse_ids], rrf_k=RRF_K, top_k=n)
    return [int(x["chunk_index"]) for x in fused][:k]


def take_unique(pool: list[int], source: list[int], needed: int) -> None:
    for cid in source:
        if len(pool) >= needed:
            return
        if cid not in pool:
            pool.append(cid)


def pool_hybrid_rrf_20(dense_ids: list[int], sparse_ids: list[int]) -> list[int]:
    return rrf_top(dense_ids, sparse_ids, POOL_K)


def pool_head_then_fill(
    dense_ids: list[int],
    sparse_ids: list[int],
    *,
    n_dense_head: int,
    n_sparse_head: int,
    fill_order: tuple[str, str],
) -> list[int]:
    """Take the first N dense and first M sparse ids, skip duplicates, then fill.

    Fill order is remaining dense-then-sparse or remaining sparse-then-dense,
    always walking each saved list from the start and skipping ids already taken.
    """
    pool: list[int] = []
    take_unique(pool, dense_ids[:n_dense_head], POOL_K)
    take_unique(pool, sparse_ids[:n_sparse_head], POOL_K)
    remaining = {
        "dense": dense_ids,
        "sparse": sparse_ids,
    }
    for name in fill_order:
        take_unique(pool, remaining[name], POOL_K)
    return pool


def pool_interleave_dense_sparse(dense_ids: list[int], sparse_ids: list[int]) -> list[int]:
    """Alternate dense then sparse ranks, skip duplicates, then fill dense then sparse."""
    pool: list[int] = []
    n = max(len(dense_ids), len(sparse_ids))
    for i in range(n):
        if i < len(dense_ids):
            take_unique(pool, [dense_ids[i]], POOL_K)
        if i < len(sparse_ids):
            take_unique(pool, [sparse_ids[i]], POOL_K)
        if len(pool) >= POOL_K:
            break
    take_unique(pool, dense_ids, POOL_K)
    take_unique(pool, sparse_ids, POOL_K)
    return pool


METHODS = {
    "hybrid_rrf_top20": {
        "label": "Baseline: BGE-M3 hybrid RRF top 20 (dense 30 + sparse 30, RRF k=60)",
        "fn": pool_hybrid_rrf_20,
    },
    "dense10_sparse10_fill_dense_then_sparse": {
        "label": (
            "First 10 meaning-search + first 10 word-search, skip duplicates, "
            "then fill leftover slots from remaining meaning ranks then remaining word ranks"
        ),
        "fn": lambda d, s: pool_head_then_fill(
            d, s, n_dense_head=10, n_sparse_head=10, fill_order=("dense", "sparse")
        ),
    },
    "interleave_dense_sparse_fill_dense_then_sparse": {
        "label": (
            "Alternate meaning rank 1, word rank 1, meaning rank 2, word rank 2, …; "
            "skip duplicates; fill leftover slots from remaining meaning then word ranks"
        ),
        "fn": pool_interleave_dense_sparse,
    },
    "dense15_sparse5_fill_dense_then_sparse": {
        "label": (
            "First 15 meaning-search + first 5 word-search, skip duplicates, "
            "then fill leftover slots from remaining meaning ranks then remaining word ranks"
        ),
        "fn": lambda d, s: pool_head_then_fill(
            d, s, n_dense_head=15, n_sparse_head=5, fill_order=("dense", "sparse")
        ),
    },
}


def gold_in_pool(pool: list[int], gold: set[int]) -> bool:
    return any(cid in gold for cid in pool)


def load_qwen_scores(path: Path) -> dict[str, dict[int, float]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, dict[int, float]] = {}
    for q in payload["questions"]:
        scores: dict[int, float] = {}
        for c in q.get("candidates") or []:
            scores[int(c["chunk_index"])] = float(c["rerank_score"])
        out[q["id"]] = scores
    return out


def coverage_for_question(hq: dict, method_fn) -> dict:
    gold = set(int(i) for i in hq["gold_chunk_indexes"])
    dense_ids = ranked_ids(hq["dense_candidates"])
    sparse_ids = ranked_ids(hq["sparse_candidates"])
    pool = method_fn(dense_ids, sparse_ids)
    gold_hits = [cid for cid in pool if cid in gold]
    dense_gold_rank = next((i for i, cid in enumerate(dense_ids, start=1) if cid in gold), None)
    sparse_gold_rank = next((i for i, cid in enumerate(sparse_ids, start=1) if cid in gold), None)
    rrf_gold_rank = next((i for i, cid in enumerate(rrf_top(dense_ids, sparse_ids, 60), start=1) if cid in gold), None)
    return {
        "id": hq["id"],
        "gold_chunk_indexes": sorted(gold),
        "n_pool": len(pool),
        "gold_in_pool": bool(gold_hits),
        "gold_in_pool_ids": gold_hits,
        "pool_position": next((i for i, cid in enumerate(pool, start=1) if cid in gold), None),
        "dense_gold_rank": dense_gold_rank,
        "sparse_gold_rank": sparse_gold_rank,
        "hybrid_rrf_gold_rank": rrf_gold_rank,
        "dense_n": len(dense_ids),
        "sparse_n": len(sparse_ids),
        "pool": pool,
    }


def choose_rule(method_totals: dict[str, dict]) -> str:
    """One fixed rule for all books: maximize total golds in the 20, then fewest losses vs baseline."""
    baseline = "hybrid_rrf_top20"
    best = baseline
    best_key = (
        method_totals[baseline]["n_gold_in_pool_all_books"],
        -method_totals[baseline]["n_lost_vs_baseline_all_books"],
        -method_totals[baseline]["n_books_worse_than_baseline"],
    )
    for name, tot in method_totals.items():
        if name == baseline:
            continue
        key = (
            tot["n_gold_in_pool_all_books"],
            -tot["n_lost_vs_baseline_all_books"],
            -tot["n_books_worse_than_baseline"],
        )
        if key > best_key:
            best = name
            best_key = key
    return best


def simulate_rerank(pool: list[int], scores: dict[int, float], gold: set[int]) -> dict:
    missing = [cid for cid in pool if cid not in scores]
    if missing:
        return {
            "complete_saved_scores": False,
            "missing_chunk_indexes": missing,
            "first_gold_rank": None,
            "hit_at_1": False,
            "hit_at_5": False,
            "hit_at_10": False,
        }
    ranked = sorted(pool, key=lambda cid: (-scores[cid], cid))
    rank = first_gold_rank(ranked[:10], gold)
    return {
        "complete_saved_scores": True,
        "missing_chunk_indexes": [],
        "first_gold_rank": rank,
        "hit_at_1": hit_at(rank, 1),
        "hit_at_5": hit_at(rank, 5),
        "hit_at_10": hit_at(rank, 10),
        "top10": ranked[:10],
    }


def main() -> int:
    coverage_books = []
    per_method_ids: dict[str, dict[str, set[str]]] = {m: {} for m in METHODS}
    eval_hashes = {}

    for spec in BOOKS:
        hybrid = json.loads(spec["hybrid"].read_text(encoding="utf-8"))
        eval_hashes[spec["book_id"]] = {
            "eval_sha256": sha256_file(spec["eval"]),
            "hybrid_sha256": sha256_file(spec["hybrid"]),
            "qwen_sha256": sha256_file(spec["qwen"]),
        }
        questions = hybrid["questions"]
        method_rows = {}
        for method_name, meta in METHODS.items():
            rows = [coverage_for_question(q, meta["fn"]) for q in questions]
            in_ids = {r["id"] for r in rows if r["gold_in_pool"]}
            per_method_ids[method_name][spec["book_id"]] = in_ids
            method_rows[method_name] = {
                "n_gold_in_pool": len(in_ids),
                "gold_in_ids": sorted(in_ids),
                "gold_out_ids": sorted(r["id"] for r in rows if not r["gold_in_pool"]),
                "questions": rows,
            }
        baseline_ids = per_method_ids["hybrid_rrf_top20"][spec["book_id"]]
        vs_baseline = {}
        for method_name in METHODS:
            ids = per_method_ids[method_name][spec["book_id"]]
            vs_baseline[method_name] = {
                "gained_ids": sorted(ids - baseline_ids),
                "lost_ids": sorted(baseline_ids - ids),
                "n_gained": len(ids - baseline_ids),
                "n_lost": len(baseline_ids - ids),
            }
        focus = {}
        for qid in FOCUS_IDS:
            if not any(q["id"] == qid for q in questions):
                continue
            focus[qid] = {
                method_name: next(r for r in method_rows[method_name]["questions"] if r["id"] == qid)
                for method_name in METHODS
            }
        coverage_books.append(
            {
                "book_id": spec["book_id"],
                "n_questions": len(questions),
                "hashes": eval_hashes[spec["book_id"]],
                "methods": {
                    name: {
                        "label": METHODS[name]["label"],
                        "n_gold_in_pool": method_rows[name]["n_gold_in_pool"],
                        "gold_out_ids": method_rows[name]["gold_out_ids"],
                        "questions": method_rows[name]["questions"],
                    }
                    for name in METHODS
                },
                "vs_hybrid_rrf_top20": vs_baseline,
                "focus_questions": focus,
            }
        )

    method_totals = {}
    for method_name in METHODS:
        n_in = sum(b["methods"][method_name]["n_gold_in_pool"] for b in coverage_books)
        n_lost = sum(b["vs_hybrid_rrf_top20"][method_name]["n_lost"] for b in coverage_books)
        n_gained = sum(b["vs_hybrid_rrf_top20"][method_name]["n_gained"] for b in coverage_books)
        n_worse = sum(
            1
            for b in coverage_books
            if b["methods"][method_name]["n_gold_in_pool"]
            < b["methods"]["hybrid_rrf_top20"]["n_gold_in_pool"]
        )
        method_totals[method_name] = {
            "label": METHODS[method_name]["label"],
            "n_gold_in_pool_all_books": n_in,
            "n_gained_vs_baseline_all_books": n_gained,
            "n_lost_vs_baseline_all_books": n_lost,
            "n_books_worse_than_baseline": n_worse,
            "by_book": {b["book_id"]: b["methods"][method_name]["n_gold_in_pool"] for b in coverage_books},
        }

    chosen = choose_rule(method_totals)
    coverage_path = OUTPUT_DIR / "qwen_pool_selection_coverage_comparison.json"
    coverage_payload = {
        "experiment": "qwen_pool_selection_coverage_offline",
        "pool_k": POOL_K,
        "used_saved_lists_only": True,
        "did_not_overwrite_baselines": True,
        "method_order": list(METHODS),
        "methods": {name: {"label": METHODS[name]["label"]} for name in METHODS},
        "fill_documentation": {
            "dense10_sparse10_fill_dense_then_sparse": [
                "1. Append BGE-M3 dense ranks 1–10 in order, skipping duplicates.",
                "2. Append BGE-M3 sparse ranks 1–10 in order, skipping duplicates.",
                "3. If fewer than 20, append remaining dense ranks 11–30, skipping duplicates.",
                "4. If still fewer than 20, append remaining sparse ranks 11–30, skipping duplicates.",
            ],
            "interleave_dense_sparse_fill_dense_then_sparse": [
                "1. Walk rank i = 1, 2, … adding dense[i] then sparse[i], skipping duplicates, until 20.",
                "2. If fewer than 20, fill remaining dense ranks then remaining sparse ranks.",
            ],
            "dense15_sparse5_fill_dense_then_sparse": [
                "1. Append dense ranks 1–15, skipping duplicates.",
                "2. Append sparse ranks 1–5, skipping duplicates.",
                "3. Fill remaining dense ranks, then remaining sparse ranks.",
            ],
        },
        "selection_rule": {
            "chosen_method": chosen,
            "reason": (
                "Pick the rule with the most gold passages across all four books, "
                "then the fewest losses versus hybrid top 20, then the fewest books "
                "where coverage is worse than the baseline. Same rule for every book."
            ),
        },
        "totals": method_totals,
        "books": coverage_books,
    }
    coverage_path.write_text(json.dumps(coverage_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # Phase 2: reuse saved Qwen scores for baseline vs chosen only.
    score_books = []
    missing_all = []
    for spec, cov in zip(BOOKS, coverage_books):
        hybrid = json.loads(spec["hybrid"].read_text(encoding="utf-8"))
        scores_by_q = load_qwen_scores(spec["qwen"])
        qwen_source = spec["qwen"].name
        chosen_fn = METHODS[chosen]["fn"]
        baseline_fn = METHODS["hybrid_rrf_top20"]["fn"]
        q_rows = []
        n_complete = 0
        ranks_complete: list[int | None] = []
        base_ranks_complete: list[int | None] = []
        for hq in hybrid["questions"]:
            gold = set(int(i) for i in hq["gold_chunk_indexes"])
            dense_ids = ranked_ids(hq["dense_candidates"])
            sparse_ids = ranked_ids(hq["sparse_candidates"])
            base_pool = baseline_fn(dense_ids, sparse_ids)
            chosen_pool = chosen_fn(dense_ids, sparse_ids)
            scores = scores_by_q.get(hq["id"], {})
            base_sim = simulate_rerank(base_pool, scores, gold)
            chosen_sim = simulate_rerank(chosen_pool, scores, gold)
            missing_detail = [
                {
                    "chunk_index": cid,
                    "in_dense": cid in dense_ids,
                    "dense_rank": next((i for i, x in enumerate(dense_ids, start=1) if x == cid), None),
                    "in_sparse": cid in sparse_ids,
                    "sparse_rank": next((i for i, x in enumerate(sparse_ids, start=1) if x == cid), None),
                    "in_hybrid_top20": cid in base_pool,
                }
                for cid in chosen_sim["missing_chunk_indexes"]
            ]
            if chosen_sim["complete_saved_scores"]:
                n_complete += 1
                ranks_complete.append(chosen_sim["first_gold_rank"])
            else:
                missing_all.append(
                    {
                        "book_id": spec["book_id"],
                        "id": hq["id"],
                        "missing_chunk_indexes": chosen_sim["missing_chunk_indexes"],
                        "missing_detail": missing_detail,
                    }
                )
            if base_sim["complete_saved_scores"]:
                base_ranks_complete.append(base_sim["first_gold_rank"])
            q_rows.append(
                {
                    "id": hq["id"],
                    "gold_in_baseline_pool": gold_in_pool(base_pool, gold),
                    "gold_in_chosen_pool": gold_in_pool(chosen_pool, gold),
                    "baseline_sim": {k: v for k, v in base_sim.items() if k != "top10"},
                    "chosen_sim": {k: v for k, v in chosen_sim.items() if k != "top10"},
                    "chosen_missing_detail": missing_detail,
                }
            )
        score_books.append(
            {
                "book_id": spec["book_id"],
                "qwen_score_file": qwen_source,
                "n_questions": len(q_rows),
                "n_questions_with_complete_chosen_scores": n_complete,
                "baseline_metrics_on_complete_baseline_scores_only": {
                    "n": len(base_ranks_complete),
                    "n_hit@1": sum(1 for r in base_ranks_complete if hit_at(r, 1)),
                    "n_hit@5": sum(1 for r in base_ranks_complete if hit_at(r, 5)),
                    "n_hit@10": sum(1 for r in base_ranks_complete if hit_at(r, 10)),
                    "mrr@10": sum(mrr_from_rank(r, 10) for r in base_ranks_complete) / len(base_ranks_complete)
                    if base_ranks_complete
                    else None,
                    "note": "Uses saved Qwen scores on the hybrid top-20 pool. Pride scores exist only for that pool.",
                },
                "chosen_metrics_if_all_scores_present": {
                    "complete": n_complete == len(q_rows),
                    "n_complete": n_complete,
                    "n_hit@1": sum(1 for r in ranks_complete if hit_at(r, 1)) if n_complete == len(q_rows) else None,
                    "n_hit@5": sum(1 for r in ranks_complete if hit_at(r, 5)) if n_complete == len(q_rows) else None,
                    "n_hit@10": sum(1 for r in ranks_complete if hit_at(r, 10)) if n_complete == len(q_rows) else None,
                },
                "questions": q_rows,
            }
        )

    score_path = OUTPUT_DIR / "qwen_pool_selection_chosen_rule_saved_score_gaps.json"
    score_payload = {
        "experiment": "qwen_pool_selection_chosen_rule_saved_scores",
        "chosen_method": chosen,
        "chosen_label": METHODS[chosen]["label"],
        "new_model_pass_run": False,
        "n_questions_missing_at_least_one_saved_score": len(missing_all),
        "missing_scores": missing_all,
        "books": score_books,
        "instruction": (
            "Do not run a new Qwen pass unless asked. "
            "Hit@K for the chosen pool is reported only when every selected passage already has a saved score."
        ),
    }
    score_path.write_text(json.dumps(score_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print("Coverage (gold in 20-passage list) /30")
    header = f"{'method':48} " + " ".join(f"{b['book_id'][:12]:>12}" for b in coverage_books) + "  total"
    print(header)
    for name, tot in method_totals.items():
        cells = " ".join(f"{tot['by_book'][b['book_id']]:12d}" for b in coverage_books)
        mark = "  <- chosen" if name == chosen else ""
        print(f"{name:48} {cells}  {tot['n_gold_in_pool_all_books']:5d}{mark}")
    print(f"Wrote {coverage_path}")
    print(f"Wrote {score_path}")
    print(f"Chosen: {chosen}")
    print(f"Questions needing new Qwen scores: {len(missing_all)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
