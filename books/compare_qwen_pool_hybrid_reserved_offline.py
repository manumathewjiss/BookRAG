"""
Offline BookRAG pool experiment: reserve hybrid slots, then alternate meaning/word.

Rules were chosen before looking at coverage:
  - hybrid_rrf_top20: current baseline
  - interleave_dense_sparse: previous alternating 20
  - hybrid8_then_interleave: first 8 hybrid RRF, then zipper meaning/word to 20
  - hybrid10_then_interleave: first 10 hybrid RRF, then zipper meaning/word to 20

8 and 10 are round splits (40% / 50% reserved for fusion). Same rule for every
book and question. No per-ID exceptions.

Uses saved BGE-M3 lists only. Does not run models or overwrite baselines.
"""

from __future__ import annotations

import json
from pathlib import Path

from compare_qwen_pool_selection_offline import (
    BOOKS,
    gold_in_pool,
    load_qwen_scores,
    pool_hybrid_rrf_20,
    pool_interleave_dense_sparse,
    ranked_ids,
    rrf_top,
    sha256_file,
    take_unique,
)

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "outputs"
POOL_K = 20
FOCUS_IDS = ("pp_003", "pp_021", "pp_028", "bg_003", "bg_010", "bg_025")
PRIDE_EXTRA_QWEN = (
    OUTPUT_DIR / "pride_and_prejudice_qwen3_reranker_0_6b_alternating_pool20_results.json",
    OUTPUT_DIR / "pride_and_prejudice_qwen3_reranker_0_6b_alternating_pool20_new_scores.json",
)


def pool_hybrid_then_interleave(
    dense_ids: list[int],
    sparse_ids: list[int],
    *,
    n_hybrid: int,
) -> list[int]:
    """Take the first n_hybrid hybrid RRF passages, then fill by alternating meaning/word."""
    pool: list[int] = []
    take_unique(pool, rrf_top(dense_ids, sparse_ids, n_hybrid), POOL_K)
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


# Exact rules, fixed before coverage was computed.
METHODS = {
    "hybrid_rrf_top20": {
        "label": "Current hybrid RRF top 20 (dense 30 + sparse 30, RRF k=60)",
        "fn": pool_hybrid_rrf_20,
    },
    "interleave_dense_sparse": {
        "label": (
            "Alternate meaning rank 1, word rank 1, meaning rank 2, word rank 2, … "
            "until 20 unique passages; fill leftover meaning then word ranks"
        ),
        "fn": pool_interleave_dense_sparse,
    },
    "hybrid8_then_interleave": {
        "label": (
            "Reserve the first 8 hybrid RRF passages, then fill remaining slots by "
            "alternating meaning and word ranks (skip duplicates; leftover meaning then word)"
        ),
        "fn": lambda d, s: pool_hybrid_then_interleave(d, s, n_hybrid=8),
    },
    "hybrid10_then_interleave": {
        "label": (
            "Reserve the first 10 hybrid RRF passages, then fill remaining slots by "
            "alternating meaning and word ranks (skip duplicates; leftover meaning then word)"
        ),
        "fn": lambda d, s: pool_hybrid_then_interleave(d, s, n_hybrid=10),
    },
}


def merge_qwen_scores(paths: list[Path]) -> dict[str, dict[int, float]]:
    merged: dict[str, dict[int, float]] = {}
    for path in paths:
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        if "questions" in payload:
            for q in payload["questions"]:
                qid = q["id"]
                rec = merged.setdefault(qid, {})
                if "candidates" in q:
                    for c in q["candidates"]:
                        rec[int(c["chunk_index"])] = float(c["rerank_score"])
                if "scores" in q:
                    for cid, score in q["scores"].items():
                        rec[int(cid)] = float(score)
        else:
            recs = load_qwen_scores(path)
            for qid, scores in recs.items():
                merged.setdefault(qid, {}).update(scores)
    return merged


def qwen_paths_for_book(spec: dict) -> list[Path]:
    paths = [spec["qwen"]]
    if spec["book_id"] == "pride_and_prejudice":
        paths.extend(PRIDE_EXTRA_QWEN)
    return paths


def cover_question(hq: dict, method_fn) -> dict:
    gold = set(int(i) for i in hq["gold_chunk_indexes"])
    dense_ids = ranked_ids(hq["dense_candidates"])
    sparse_ids = ranked_ids(hq["sparse_candidates"])
    pool = method_fn(dense_ids, sparse_ids)
    gold_hits = [cid for cid in pool if cid in gold]
    return {
        "id": hq["id"],
        "gold_chunk_indexes": sorted(gold),
        "n_pool": len(pool),
        "gold_in_pool": bool(gold_hits),
        "gold_in_pool_ids": gold_hits,
        "pool_position": next((i for i, cid in enumerate(pool, start=1) if cid in gold), None),
        "dense_gold_rank": next((i for i, cid in enumerate(dense_ids, start=1) if cid in gold), None),
        "sparse_gold_rank": next((i for i, cid in enumerate(sparse_ids, start=1) if cid in gold), None),
        "hybrid_rrf_gold_rank": next(
            (i for i, cid in enumerate(rrf_top(dense_ids, sparse_ids, 60), start=1) if cid in gold),
            None,
        ),
        "pool": pool,
    }


def main() -> int:
    coverage_books = []
    in_ids: dict[str, dict[str, set[str]]] = {m: {} for m in METHODS}

    for spec in BOOKS:
        hybrid = json.loads(spec["hybrid"].read_text(encoding="utf-8"))
        questions = hybrid["questions"]
        score_paths = qwen_paths_for_book(spec)
        saved_scores = merge_qwen_scores(score_paths)
        method_block = {}
        for name, meta in METHODS.items():
            rows = [cover_question(q, meta["fn"]) for q in questions]
            present = {r["id"] for r in rows if r["gold_in_pool"]}
            in_ids[name][spec["book_id"]] = present
            n_scored_slots = 0
            n_unscored_slots = 0
            n_q_incomplete = 0
            unscored_by_q = []
            for r in rows:
                have = saved_scores.get(r["id"], {})
                missing = [cid for cid in r["pool"] if cid not in have]
                n_scored_slots += len(r["pool"]) - len(missing)
                n_unscored_slots += len(missing)
                if missing:
                    n_q_incomplete += 1
                    unscored_by_q.append({"id": r["id"], "missing_chunk_indexes": missing})
            method_block[name] = {
                "label": meta["label"],
                "n_gold_in_pool": len(present),
                "gold_out_ids": sorted(r["id"] for r in rows if not r["gold_in_pool"]),
                "n_selected_passages": sum(r["n_pool"] for r in rows),
                "n_selected_with_saved_qwen_score": n_scored_slots,
                "n_selected_needing_qwen_score": n_unscored_slots,
                "n_questions_with_any_unscored_passage": n_q_incomplete,
                "unscored_by_question": unscored_by_q,
                "questions": [
                    {k: v for k, v in r.items() if k != "pool"} | {"n_pool": r["n_pool"]}
                    for r in rows
                ],
            }
        baseline = in_ids["hybrid_rrf_top20"][spec["book_id"]]
        vs = {}
        for name in METHODS:
            ids = in_ids[name][spec["book_id"]]
            vs[name] = {
                "gained_ids": sorted(ids - baseline),
                "lost_ids": sorted(baseline - ids),
            }
        focus = {}
        for qid in FOCUS_IDS:
            if not any(q["id"] == qid for q in questions):
                continue
            focus[qid] = {
                name: next(r for r in method_block[name]["questions"] if r["id"] == qid)
                for name in METHODS
            }
        coverage_books.append(
            {
                "book_id": spec["book_id"],
                "n_questions": len(questions),
                "hashes": {
                    "eval_sha256": sha256_file(spec["eval"]),
                    "hybrid_sha256": sha256_file(spec["hybrid"]),
                    "qwen_score_files": [str(p) for p in score_paths if p.exists()],
                    "qwen_sha256": [sha256_file(p) for p in score_paths if p.exists()],
                },
                "methods": method_block,
                "vs_hybrid_rrf_top20": vs,
                "focus_questions": focus,
            }
        )

    totals = {}
    for name in METHODS:
        n_in = sum(b["methods"][name]["n_gold_in_pool"] for b in coverage_books)
        n_need = sum(b["methods"][name]["n_selected_needing_qwen_score"] for b in coverage_books)
        n_have = sum(b["methods"][name]["n_selected_with_saved_qwen_score"] for b in coverage_books)
        n_lost = sum(len(b["vs_hybrid_rrf_top20"][name]["lost_ids"]) for b in coverage_books)
        n_gained = sum(len(b["vs_hybrid_rrf_top20"][name]["gained_ids"]) for b in coverage_books)
        totals[name] = {
            "label": METHODS[name]["label"],
            "n_gold_in_pool_all_books": n_in,
            "by_book": {b["book_id"]: b["methods"][name]["n_gold_in_pool"] for b in coverage_books},
            "n_gained_vs_hybrid": n_gained,
            "n_lost_vs_hybrid": n_lost,
            "n_selected_with_saved_qwen_score": n_have,
            "n_selected_needing_qwen_score": n_need,
        }

    goal_ids = {"pp_003", "pp_021", "bg_003"}
    goal_ok = {}
    for name in METHODS:
        ok = True
        detail = {}
        for b in coverage_books:
            for qid in goal_ids:
                if qid not in b["focus_questions"]:
                    continue
                in_pool = b["focus_questions"][qid][name]["gold_in_pool"]
                detail[qid] = in_pool
                if not in_pool:
                    ok = False
        goal_ok[name] = {"keeps_pp_003_pp_021_bg_003": ok, "detail": detail}

    # Recommend only if a non-baseline rule keeps all three goal golds, does not
    # lose more golds than it gains vs hybrid, and is at least as good as hybrid
    # on every book or strictly better in total without dropping Gita coverage.
    recommendation = {
        "chosen_method": None,
        "recommend_change": False,
        "reason": "",
    }
    candidates = []
    for name in METHODS:
        if name == "hybrid_rrf_top20":
            continue
        if not goal_ok[name]["keeps_pp_003_pp_021_bg_003"]:
            continue
        gita = next(b for b in coverage_books if b["book_id"] == "bhagavad_gita")
        pride = next(b for b in coverage_books if b["book_id"] == "pride_and_prejudice")
        if gita["methods"][name]["n_gold_in_pool"] < gita["methods"]["hybrid_rrf_top20"]["n_gold_in_pool"]:
            continue
        if pride["methods"][name]["n_gold_in_pool"] < pride["methods"]["hybrid_rrf_top20"]["n_gold_in_pool"]:
            continue
        if totals[name]["n_gold_in_pool_all_books"] < totals["hybrid_rrf_top20"]["n_gold_in_pool_all_books"]:
            continue
        candidates.append(name)
    if candidates:
        best = max(
            candidates,
            key=lambda n: (
                totals[n]["n_gold_in_pool_all_books"],
                -totals[n]["n_lost_vs_hybrid"],
                -totals[n]["n_selected_needing_qwen_score"],
            ),
        )
        recommendation = {
            "chosen_method": best,
            "recommend_change": True,
            "reason": (
                f"{best} keeps pp_003, pp_021, and bg_003, does not cut Gita or Pride "
                "coverage below hybrid, and has the best four-book gold count among those rules."
            ),
        }
    else:
        recommendation = {
            "chosen_method": None,
            "recommend_change": False,
            "reason": (
                "No tested non-baseline rule both keeps pp_003, pp_021, and bg_003 and "
                "avoids dropping Gita or Pride coverage versus hybrid top 20. "
                "Leave the current pipeline unchanged."
            ),
        }

    detail_path = OUTPUT_DIR / "qwen_pool_hybrid_reserved_then_interleave_comparison.json"
    summary_path = OUTPUT_DIR / "qwen_pool_hybrid_reserved_then_interleave_summary.json"
    payload = {
        "experiment": "qwen_pool_hybrid_reserved_then_interleave_offline",
        "pool_k": POOL_K,
        "used_saved_lists_only": True,
        "ran_qwen": False,
        "did_not_overwrite_baselines": True,
        "rules_fixed_before_coverage": True,
        "rule_choice_notes": (
            "hybrid8 and hybrid10 reserve 40% or 50% of the 20 slots for the strongest "
            "hybrid ranks, then fill by the same alternating meaning/word walk used before. "
            "Round splits were chosen in advance, not by inspecting question IDs."
        ),
        "methods": {name: {"label": METHODS[name]["label"]} for name in METHODS},
        "goal_ids": sorted(goal_ids),
        "goal_status": goal_ok,
        "totals": totals,
        "recommendation": recommendation,
        "books": coverage_books,
    }
    detail_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    summary = {
        "experiment": payload["experiment"],
        "ran_qwen": False,
        "rules_fixed_before_coverage": True,
        "methods": payload["methods"],
        "coverage_out_of_30": {name: tot["by_book"] for name, tot in totals.items()},
        "coverage_total_out_of_120": {name: tot["n_gold_in_pool_all_books"] for name, tot in totals.items()},
        "gained_lost_vs_hybrid": {
            b["book_id"]: {
                name: b["vs_hybrid_rrf_top20"][name]
                for name in METHODS
                if name != "hybrid_rrf_top20"
            }
            for b in coverage_books
        },
        "focus": {
            qid: {
                b["book_id"]: {
                    name: {
                        "gold_in_pool": rec["gold_in_pool"],
                        "pool_position": rec["pool_position"],
                        "dense_gold_rank": rec["dense_gold_rank"],
                        "sparse_gold_rank": rec["sparse_gold_rank"],
                        "hybrid_rrf_gold_rank": rec["hybrid_rrf_gold_rank"],
                    }
                    for name, rec in b["focus_questions"][qid].items()
                }
                for b in coverage_books
                if qid in b["focus_questions"]
            }
            for qid in FOCUS_IDS
        },
        "saved_qwen_score_gaps": {
            b["book_id"]: {
                name: {
                    "n_selected_with_saved_qwen_score": b["methods"][name]["n_selected_with_saved_qwen_score"],
                    "n_selected_needing_qwen_score": b["methods"][name]["n_selected_needing_qwen_score"],
                    "n_questions_with_any_unscored_passage": b["methods"][name][
                        "n_questions_with_any_unscored_passage"
                    ],
                    "unscored_by_question": b["methods"][name]["unscored_by_question"],
                }
                for name in METHODS
            }
            for b in coverage_books
        },
        "goal_status": goal_ok,
        "recommendation": recommendation,
        "detail_file": str(detail_path),
    }
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print("Gold in 20 /30")
    header = f"{'method':28} " + " ".join(f"{b['book_id'][:14]:>14}" for b in coverage_books) + "  total  need_qwen"
    print(header)
    for name, tot in totals.items():
        cells = " ".join(f"{tot['by_book'][b['book_id']]:14d}" for b in coverage_books)
        mark = "  <- recommend" if recommendation.get("chosen_method") == name else ""
        print(f"{name:28} {cells}  {tot['n_gold_in_pool_all_books']:5d}  {tot['n_selected_needing_qwen_score']:5d}{mark}")
    print("recommend", recommendation)
    print("Wrote", detail_path)
    print("Wrote", summary_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
