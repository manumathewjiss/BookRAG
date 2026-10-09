"""
Saved-score Qwen comparison of three 20-passage pools.

Does not run models or overwrite baselines.
"""

from __future__ import annotations

import json
from pathlib import Path

from compare_qwen_pool_hybrid_reserved_offline import (
    METHODS,
    PRIDE_EXTRA_QWEN,
    merge_qwen_scores,
    pool_hybrid_then_interleave,
    qwen_paths_for_book,
)
from compare_qwen_pool_selection_offline import (
    BOOKS,
    gold_in_pool,
    pool_hybrid_rrf_20,
    ranked_ids,
    sha256_file,
)
from evaluate_retrieval_stage3 import first_gold_rank, hit_at, mrr_from_rank

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "outputs"
POOL_K = 20
FINAL_K = 10
COMPARE_METHODS = (
    "hybrid_rrf_top20",
    "hybrid8_then_interleave",
    "hybrid10_then_interleave",
)
PREV_HYBRID20 = OUTPUT_DIR / "qwen_alternating_vs_hybrid_pool20_four_book_comparison.json"


def rank_key(rank: int | None) -> int:
    return 11 if rank is None else rank


def metrics(gold_in: list[bool], ranks: list[int | None]) -> dict:
    n = len(ranks)
    return {
        "n_questions": n,
        "n_gold_reached_qwen": sum(1 for x in gold_in if x),
        "n_hit@1": sum(1 for r in ranks if hit_at(r, 1)),
        "n_hit@5": sum(1 for r in ranks if hit_at(r, 5)),
        "n_hit@10": sum(1 for r in ranks if hit_at(r, 10)),
        "mrr@10": sum(mrr_from_rank(r, 10) for r in ranks) / n if n else 0.0,
    }


def rerank_pool(pool: list[int], scores: dict[int, float], gold: set[int]) -> dict:
    missing = [cid for cid in pool if cid not in scores]
    if missing:
        return {
            "complete": False,
            "missing_chunk_indexes": missing,
            "first_gold_rank": None,
            "ranked": [],
        }
    ranked = sorted(pool, key=lambda cid: (-scores[cid], cid))
    return {
        "complete": True,
        "missing_chunk_indexes": [],
        "first_gold_rank": first_gold_rank(ranked[:FINAL_K], gold),
        "ranked": ranked,
    }


def load_saved_baseline_ranks(spec: dict) -> dict[str, dict]:
    payload = json.loads(spec["qwen"].read_text(encoding="utf-8"))
    out = {}
    for q in payload["questions"]:
        out[q["id"]] = {
            "first_gold_rank": q.get("first_gold_rank"),
            "gold_reached": bool(q.get("gold_in_hybrid_pool20") or q.get("gold_in_candidate_list")),
            "n_candidates": q.get("n_candidates"),
            "candidate_ids": [int(c["chunk_index"]) for c in q.get("candidates") or []],
        }
    return out


def load_prev_hybrid20_ranks() -> dict[str, dict[str, int | None]]:
    payload = json.loads(PREV_HYBRID20.read_text(encoding="utf-8"))
    out: dict[str, dict[str, int | None]] = {}
    for book in payload["books"]:
        out[book["book_id"]] = {
            q["id"]: q.get("hybrid_first_gold_rank") for q in book["questions"]
        }
    return out


def main() -> int:
    prev_h20 = load_prev_hybrid20_ranks()
    books_out = []
    baseline_ok_all = True

    for spec in BOOKS:
        hybrid = json.loads(spec["hybrid"].read_text(encoding="utf-8"))
        questions = hybrid["questions"]
        scores = merge_qwen_scores(qwen_paths_for_book(spec))
        saved_qwen = load_saved_baseline_ranks(spec)
        book_id = spec["book_id"]

        reconstructed_vs_saved_retrieved = []
        method_rows: dict[str, list[dict]] = {m: [] for m in COMPARE_METHODS}
        incomplete = []

        for hq in questions:
            qid = hq["id"]
            gold = set(int(i) for i in hq["gold_chunk_indexes"])
            dense_ids = ranked_ids(hq["dense_candidates"])
            sparse_ids = ranked_ids(hq["sparse_candidates"])
            pools = {
                "hybrid_rrf_top20": pool_hybrid_rrf_20(dense_ids, sparse_ids),
                "hybrid8_then_interleave": pool_hybrid_then_interleave(dense_ids, sparse_ids, n_hybrid=8),
                "hybrid10_then_interleave": pool_hybrid_then_interleave(dense_ids, sparse_ids, n_hybrid=10),
            }
            saved_retrieved = [int(h["chunk_index"]) for h in (hq.get("retrieved") or [])]
            rebuilt = pools["hybrid_rrf_top20"]
            # Pride hybrid file stored final_k=20; other books stored final_k=10.
            check_n = min(len(saved_retrieved), 20, len(rebuilt))
            if saved_retrieved[:check_n] != rebuilt[:check_n]:
                reconstructed_vs_saved_retrieved.append(
                    {
                        "id": qid,
                        "saved_retrieved_prefix": saved_retrieved[:check_n],
                        "rebuilt_hybrid20_prefix": rebuilt[:check_n],
                    }
                )

            q_scores = scores.get(qid, {})
            for name, pool in pools.items():
                sim = rerank_pool(pool, q_scores, gold)
                if not sim["complete"]:
                    incomplete.append({"id": qid, "method": name, "missing": sim["missing_chunk_indexes"]})
                in_pool = gold_in_pool(pool, gold)
                rank = sim["first_gold_rank"] if sim["complete"] else None
                method_rows[name].append(
                    {
                        "id": qid,
                        "gold_reached_qwen": in_pool,
                        "first_gold_rank": rank,
                        "hit_at_1": hit_at(rank, 1) if sim["complete"] else False,
                        "hit_at_5": hit_at(rank, 5) if sim["complete"] else False,
                        "hit_at_10": hit_at(rank, 10) if sim["complete"] else False,
                        "n_pool": len(pool),
                        "scores_complete": sim["complete"],
                    }
                )

        hybrid_rows = method_rows["hybrid_rrf_top20"]
        saved_file_mismatches = []
        prev_sim_mismatches = []
        for row in hybrid_rows:
            qid = row["id"]
            saved = saved_qwen[qid]
            prev_rank = prev_h20.get(book_id, {}).get(qid)
            if prev_rank != row["first_gold_rank"]:
                prev_sim_mismatches.append(
                    {
                        "id": qid,
                        "previous_hybrid20_simulation": prev_rank,
                        "this_run": row["first_gold_rank"],
                    }
                )
            # Pride saved Qwen file IS the hybrid top-20 run.
            # Other books' saved Qwen files are dense∪sparse union, so ranks may differ.
            if book_id == "pride_and_prejudice":
                if saved["first_gold_rank"] != row["first_gold_rank"]:
                    saved_file_mismatches.append(
                        {
                            "id": qid,
                            "saved_pool20_file": saved["first_gold_rank"],
                            "this_run": row["first_gold_rank"],
                        }
                    )
            else:
                # Exact reproduction target for non-Pride is the previous hybrid-20 simulation.
                pass

        if book_id == "pride_and_prejudice":
            baseline_ok = not saved_file_mismatches and not reconstructed_vs_saved_retrieved
            baseline_note = (
                "Reproduced the saved Pride hybrid top-20 Qwen file and the saved hybrid retrieved lists."
                if baseline_ok
                else "Pride hybrid top-20 reconstruction did not match the saved baseline."
            )
        else:
            baseline_ok = not prev_sim_mismatches and not reconstructed_vs_saved_retrieved
            union_rank_diffs = [
                {
                    "id": row["id"],
                    "saved_union_qwen_rank": saved_qwen[row["id"]]["first_gold_rank"],
                    "hybrid20_rank": row["first_gold_rank"],
                    "saved_union_n_candidates": saved_qwen[row["id"]]["n_candidates"],
                }
                for row in hybrid_rows
                if saved_qwen[row["id"]]["first_gold_rank"] != row["first_gold_rank"]
            ]
            baseline_note = (
                "Reproduced the previous hybrid top-20 saved-score simulation. "
                "The original Qwen result file used the dense∪sparse union, not hybrid top 20."
            )
            if union_rank_diffs:
                baseline_note += (
                    f" Union vs hybrid-20 rank differed on {len(union_rank_diffs)} questions "
                    "(expected if the candidate sets differ)."
                )

        if not baseline_ok:
            baseline_ok_all = False

        method_metrics = {}
        vs_hybrid = {}
        for name in COMPARE_METHODS:
            rows = method_rows[name]
            method_metrics[name] = metrics(
                [r["gold_reached_qwen"] for r in rows],
                [r["first_gold_rank"] for r in rows],
            )
            if name == "hybrid_rrf_top20":
                continue
            hy = {r["id"]: r for r in hybrid_rows}
            improved = []
            worsened = []
            for r in rows:
                old = hy[r["id"]]["first_gold_rank"]
                new = r["first_gold_rank"]
                if rank_key(new) < rank_key(old):
                    improved.append(
                        {"id": r["id"], "hybrid_rank": old, "new_rank": new}
                    )
                elif rank_key(new) > rank_key(old):
                    worsened.append(
                        {"id": r["id"], "hybrid_rank": old, "new_rank": new}
                    )
            hy_in = {r["id"] for r in hybrid_rows if r["gold_reached_qwen"]}
            new_in = {r["id"] for r in rows if r["gold_reached_qwen"]}
            vs_hybrid[name] = {
                "pool_gained_ids": sorted(new_in - hy_in),
                "pool_lost_ids": sorted(hy_in - new_in),
                "rerank_improved": improved,
                "rerank_worsened": worsened,
            }

        book_entry = {
            "book_id": book_id,
            "baseline_reproduction": {
                "ok": baseline_ok,
                "note": baseline_note,
                "hybrid_retrieved_prefix_mismatches": reconstructed_vs_saved_retrieved,
                "pride_saved_pool20_rank_mismatches": saved_file_mismatches
                if book_id == "pride_and_prejudice"
                else [],
                "previous_hybrid20_simulation_mismatches": prev_sim_mismatches,
            },
            "methods": {
                name: {
                    "label": METHODS[name]["label"],
                    **method_metrics[name],
                    "questions": method_rows[name],
                }
                for name in COMPARE_METHODS
            },
            "vs_hybrid_rrf_top20": vs_hybrid,
            "n_incomplete_score_lookups": len(incomplete),
            "incomplete": incomplete,
            "hashes": {
                "eval_sha256": sha256_file(spec["eval"]),
                "hybrid_sha256": sha256_file(spec["hybrid"]),
                "qwen_sha256": sha256_file(spec["qwen"]),
            },
        }
        if book_id != "pride_and_prejudice":
            book_entry["baseline_reproduction"]["union_qwen_vs_hybrid20_rank_diffs"] = [
                {
                    "id": row["id"],
                    "saved_union_qwen_rank": saved_qwen[row["id"]]["first_gold_rank"],
                    "hybrid20_rank": row["first_gold_rank"],
                    "saved_union_n_candidates": saved_qwen[row["id"]]["n_candidates"],
                }
                for row in hybrid_rows
                if saved_qwen[row["id"]]["first_gold_rank"] != row["first_gold_rank"]
            ]
        books_out.append(book_entry)

    # Recommend from final Qwen metrics, not list order.
    # Score: total Hit@1, then Hit@5, then Hit@10, then golds reached, then fewer worsenings.
    totals = {}
    for name in COMPARE_METHODS:
        totals[name] = {
            "n_gold_reached_qwen": sum(b["methods"][name]["n_gold_reached_qwen"] for b in books_out),
            "n_hit@1": sum(b["methods"][name]["n_hit@1"] for b in books_out),
            "n_hit@5": sum(b["methods"][name]["n_hit@5"] for b in books_out),
            "n_hit@10": sum(b["methods"][name]["n_hit@10"] for b in books_out),
            "n_rerank_worsened": sum(
                len(b["vs_hybrid_rrf_top20"][name]["rerank_worsened"])
                if name != "hybrid_rrf_top20"
                else 0
                for b in books_out
            ),
            "n_books_worse_hit1_than_hybrid": sum(
                1
                for b in books_out
                if name != "hybrid_rrf_top20"
                and b["methods"][name]["n_hit@1"] < b["methods"]["hybrid_rrf_top20"]["n_hit@1"]
            ),
            "by_book": {
                b["book_id"]: {
                    "n_gold_reached_qwen": b["methods"][name]["n_gold_reached_qwen"],
                    "n_hit@1": b["methods"][name]["n_hit@1"],
                    "n_hit@5": b["methods"][name]["n_hit@5"],
                    "n_hit@10": b["methods"][name]["n_hit@10"],
                }
                for b in books_out
            },
        }

    def score_tuple(name: str) -> tuple:
        t = totals[name]
        return (
            t["n_hit@1"],
            t["n_hit@5"],
            t["n_hit@10"],
            t["n_gold_reached_qwen"],
            -t["n_books_worse_hit1_than_hybrid"],
            -t["n_rerank_worsened"],
        )

    ranked_rules = sorted(COMPARE_METHODS, key=score_tuple, reverse=True)
    best = ranked_rules[0]
    tied = [n for n in COMPARE_METHODS if score_tuple(n) == score_tuple(best)]
    hybrid_t = score_tuple("hybrid_rrf_top20")
    if not baseline_ok_all:
        recommendation = {
            "recommend_change": False,
            "chosen_method": None,
            "reason": "Hybrid top-20 saved-score reconstruction did not match the saved baseline; no new rule is recommended.",
        }
    elif best == "hybrid_rrf_top20" or score_tuple(best) == hybrid_t:
        recommendation = {
            "recommend_change": False,
            "chosen_method": "hybrid_rrf_top20" if len(tied) == 1 or "hybrid_rrf_top20" in tied else None,
            "tied_methods": tied,
            "reason": (
                "No reserved-hybrid rule beats current hybrid top 20 on Hit@1, then Hit@5, then Hit@10, "
                "then golds reached, across all four books."
            ),
        }
    else:
        recommendation = {
            "recommend_change": True,
            "chosen_method": best if len(tied) == 1 else None,
            "tied_methods": tied,
            "reason": (
                f"{best if len(tied)==1 else 'Tied: ' + ', '.join(tied)} "
                "wins on four-book Qwen Hit@1, then Hit@5, then Hit@10, then golds in the 20. "
                "8 was not preferred merely for being listed first."
            ),
        }

    detail_path = OUTPUT_DIR / "qwen_hybrid_reserved_saved_score_rerank_comparison.json"
    summary_path = OUTPUT_DIR / "qwen_hybrid_reserved_saved_score_rerank_summary.json"
    payload = {
        "experiment": "qwen_hybrid8_hybrid10_vs_hybrid20_saved_score_rerank",
        "ran_qwen": False,
        "used_saved_qwen_scores_only": True,
        "did_not_overwrite_baselines": True,
        "final_k": FINAL_K,
        "pool_k": POOL_K,
        "methods_compared": list(COMPARE_METHODS),
        "baseline_reproduction_ok": baseline_ok_all,
        "totals": totals,
        "recommendation": recommendation,
        "books": books_out,
    }
    detail_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    summary = {
        "experiment": payload["experiment"],
        "ran_qwen": False,
        "baseline_reproduction_ok": baseline_ok_all,
        "methods_compared": {
            name: METHODS[name]["label"] for name in COMPARE_METHODS
        },
        "by_book": {
            b["book_id"]: {
                "baseline_reproduction": {
                    "ok": b["baseline_reproduction"]["ok"],
                    "note": b["baseline_reproduction"]["note"],
                    "n_previous_simulation_mismatches": len(
                        b["baseline_reproduction"]["previous_hybrid20_simulation_mismatches"]
                    ),
                    "n_pride_saved_file_mismatches": len(
                        b["baseline_reproduction"]["pride_saved_pool20_rank_mismatches"]
                    ),
                    "n_retrieved_prefix_mismatches": len(
                        b["baseline_reproduction"]["hybrid_retrieved_prefix_mismatches"]
                    ),
                    "n_union_vs_hybrid20_rank_diffs": len(
                        b["baseline_reproduction"].get("union_qwen_vs_hybrid20_rank_diffs") or []
                    ),
                },
                "metrics": {
                    name: {
                        k: b["methods"][name][k]
                        for k in (
                            "n_gold_reached_qwen",
                            "n_hit@1",
                            "n_hit@5",
                            "n_hit@10",
                            "mrr@10",
                        )
                    }
                    for name in COMPARE_METHODS
                },
                "vs_hybrid_rrf_top20": {
                    name: {
                        "pool_gained_ids": v["pool_gained_ids"],
                        "pool_lost_ids": v["pool_lost_ids"],
                        "rerank_improved_ids": [x["id"] for x in v["rerank_improved"]],
                        "rerank_worsened_ids": [x["id"] for x in v["rerank_worsened"]],
                        "rerank_improved": v["rerank_improved"],
                        "rerank_worsened": v["rerank_worsened"],
                    }
                    for name, v in b["vs_hybrid_rrf_top20"].items()
                },
            }
            for b in books_out
        },
        "four_book_totals": totals,
        "recommendation": recommendation,
        "detail_file": str(detail_path),
    }
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print("baseline_ok", baseline_ok_all)
    print(f"{'book':22} {'rule':28} reach hit1/5/10")
    for b in books_out:
        for name in COMPARE_METHODS:
            m = b["methods"][name]
            print(
                f"{b['book_id']:22} {name:28} {m['n_gold_reached_qwen']:2d} "
                f"{m['n_hit@1']:2d}/{m['n_hit@5']:2d}/{m['n_hit@10']:2d}  "
                f"base_ok={b['baseline_reproduction']['ok']}"
            )
        for name, v in b["vs_hybrid_rrf_top20"].items():
            print(
                f"  vs hybrid {name}: +{v['pool_gained_ids']} -{v['pool_lost_ids']} "
                f"better {[x['id'] for x in v['rerank_improved']]} "
                f"worse {[x['id'] for x in v['rerank_worsened']]}"
            )
    print("totals", {n: {k: totals[n][k] for k in ('n_gold_reached_qwen','n_hit@1','n_hit@5','n_hit@10')} for n in COMPARE_METHODS})
    print("recommend", recommendation)
    print("Wrote", detail_path)
    print("Wrote", summary_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
