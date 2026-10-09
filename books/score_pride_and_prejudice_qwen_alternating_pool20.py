"""
Score missing Pride alternating-20 passages, then compare hybrid vs alternating pools.

Reuses saved Qwen scores. Does not overwrite earlier Pride hybrid-pool20 files
or change production search.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from compare_qwen_pool_selection_offline import (
    BOOKS,
    METHODS,
    POOL_K,
    gold_in_pool,
    load_qwen_scores,
    pool_hybrid_rrf_20,
    pool_interleave_dense_sparse,
    ranked_ids,
    sha256_file,
    simulate_rerank,
)
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
CHOSEN = "interleave_dense_sparse_fill_dense_then_sparse"
FINAL_K = 10


def rank_key(rank: int | None) -> int:
    return 11 if rank is None else rank


def main() -> int:
    hybrid_path = OUTPUT_DIR / "pride_and_prejudice_bge_m3_hybrid_retrieval_results.json"
    saved_qwen_path = OUTPUT_DIR / "pride_and_prejudice_qwen3_reranker_0_6b_pool20_results.json"
    chunks_path = OUTPUT_DIR / "pride_and_prejudice_stage1_chunks.json"
    eval_path = OUTPUT_DIR / "pride_and_prejudice_retrieval_eval_frozen_30.json"
    new_scores_path = OUTPUT_DIR / "pride_and_prejudice_qwen3_reranker_0_6b_alternating_pool20_new_scores.json"
    results_path = OUTPUT_DIR / "pride_and_prejudice_qwen3_reranker_0_6b_alternating_pool20_results.json"
    summary_path = OUTPUT_DIR / "pride_and_prejudice_qwen3_reranker_0_6b_alternating_pool20_summary.json"
    compare_path = OUTPUT_DIR / "qwen_alternating_vs_hybrid_pool20_four_book_comparison.json"

    for path in (results_path, summary_path, new_scores_path, compare_path, saved_qwen_path, hybrid_path):
        if path in (saved_qwen_path, hybrid_path):
            continue
        # never write over the original Pride hybrid-pool20 Qwen files
        if path.name == "pride_and_prejudice_qwen3_reranker_0_6b_pool20_results.json":
            raise RuntimeError("refusing to overwrite baseline Pride Qwen results")

    free = disk_free_gb(Path.home())
    print(f"Disk free: {free:.1f} GiB")
    if free < 1.0:
        print("Refusing: under 1 GiB free.")
        return 2

    hybrid = json.loads(hybrid_path.read_text(encoding="utf-8"))
    chunks = load_chunks(chunks_path)
    saved_scores = load_qwen_scores(saved_qwen_path)
    questions = hybrid["questions"]

    to_score: list[tuple[str, str, list[int]]] = []
    n_reuse = 0
    for hq in questions:
        qid = hq["id"]
        dense_ids = ranked_ids(hq["dense_candidates"])
        sparse_ids = ranked_ids(hq["sparse_candidates"])
        alt_pool = pool_interleave_dense_sparse(dense_ids, sparse_ids)
        have = saved_scores.get(qid, {})
        missing = [cid for cid in alt_pool if cid not in have]
        n_reuse += len(alt_pool) - len(missing)
        if missing:
            to_score.append((qid, hq["question"], missing))

    n_new = sum(len(m) for _, _, m in to_score)
    print(f"Reuse {n_reuse} saved scores; score {n_new} new passages across {len(to_score)} questions")

    device, dtype, reason = choose_device("mps")
    print(f"Device={device} dtype={dtype} ({reason})")
    reranker = Qwen3Reranker(MODEL_ID, device=device, dtype=dtype)

    new_scores: dict[str, dict[int, float]] = {}
    t0 = time.perf_counter()
    score_seconds = 0.0
    for qid, question, missing in to_score:
        texts = []
        for cid in missing:
            if cid not in chunks:
                raise RuntimeError(f"{qid}: missing Stage 1 chunk {cid}")
            texts.append(chunks[cid]["text"])
        ts = time.perf_counter()
        scores = reranker.score_pairs(question, texts, batch_size=2)
        score_seconds += time.perf_counter() - ts
        new_scores[qid] = {cid: float(s) for cid, s in zip(missing, scores)}
        print(f"{qid} new={len(missing)} {time.perf_counter() - ts:.1f}s")

    elapsed_score = time.perf_counter() - t0
    new_scores_payload = {
        "book_id": "pride_and_prejudice",
        "purpose": "Qwen scores for alternating-20 passages that were not in the saved hybrid top-20 run",
        "reranker_model": MODEL_ID,
        "device": device,
        "dtype": str(dtype).replace("torch.", ""),
        "batch_size": 2,
        "n_new_pairs": n_new,
        "n_questions_with_new_pairs": len(to_score),
        "n_reused_saved_pairs": n_reuse,
        "score_seconds": round(score_seconds, 3),
        "processing_time_seconds": round(elapsed_score, 3),
        "eval_sha256": sha256_file(eval_path),
        "hybrid_sha256": sha256_file(hybrid_path),
        "saved_qwen_sha256": sha256_file(saved_qwen_path),
        "chunks_sha256": sha256_file(chunks_path),
        "questions": [
            {
                "id": qid,
                "scores": {str(cid): score for cid, score in sorted(pairs.items())},
            }
            for qid, pairs in new_scores.items()
        ],
    }
    new_scores_path.write_text(json.dumps(new_scores_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {new_scores_path}")

    alt_rows = []
    ranks: list[int | None] = []
    n_gold_in = 0
    n_new_used = 0
    n_reused_used = 0
    for hq in questions:
        qid = hq["id"]
        gold = set(int(i) for i in hq["gold_chunk_indexes"])
        dense_ids = ranked_ids(hq["dense_candidates"])
        sparse_ids = ranked_ids(hq["sparse_candidates"])
        alt_pool = pool_interleave_dense_sparse(dense_ids, sparse_ids)
        scores = dict(saved_scores.get(qid, {}))
        reused_here = [cid for cid in alt_pool if cid in saved_scores.get(qid, {})]
        new_here = [cid for cid in alt_pool if cid not in saved_scores.get(qid, {})]
        scores.update(new_scores.get(qid, {}))
        missing = [cid for cid in alt_pool if cid not in scores]
        if missing:
            raise RuntimeError(f"{qid} still missing scores: {missing}")
        n_new_used += len(new_here)
        n_reused_used += len(reused_here)
        ranked = sorted(alt_pool, key=lambda cid: (-scores[cid], cid))
        rank = first_gold_rank(ranked[:FINAL_K], gold)
        ranks.append(rank)
        gold_ids = [cid for cid in alt_pool if cid in gold]
        if gold_ids:
            n_gold_in += 1
        cands = []
        for i, cid in enumerate(ranked, start=1):
            cands.append(
                {
                    "chunk_index": cid,
                    "page": chunks[cid].get("page"),
                    "rerank_score": scores[cid],
                    "rerank_rank": i,
                    "score_source": "new" if cid in new_here else "reused_hybrid_pool20",
                    "text_preview": preview(chunks[cid]["text"]),
                }
            )
        alt_rows.append(
            {
                "id": qid,
                "question": hq["question"],
                "book_id": "pride_and_prejudice",
                "gold_chunk_indexes": sorted(gold),
                "gold_in_alternating_pool20": gold_ids,
                "gold_reached_reranker_pool20": bool(gold_ids),
                "n_candidates": len(alt_pool),
                "n_scores_reused": len(reused_here),
                "n_scores_new": len(new_here),
                "candidates": cands,
                "retrieved": [
                    {
                        "rank": c["rerank_rank"],
                        "chunk_index": c["chunk_index"],
                        "page": c["page"],
                        "rerank_score": c["rerank_score"],
                        "score_source": c["score_source"],
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
        )
        print(f"{qid} gold_in={bool(gold_ids)} rerank={rank} reused={len(reused_here)} new={len(new_here)}")

    mets = metrics_from_ranks(ranks)
    results_payload = {
        "book_id": "pride_and_prejudice",
        "embedding_family": "qwen3_reranker_0_6b_local_alternating_pool20",
        "reranker_model": MODEL_ID,
        "device": device,
        "dtype": str(dtype).replace("torch.", ""),
        "batch_size": 2,
        "candidate_source": METHODS[CHOSEN]["label"],
        "pool_k": POOL_K,
        "final_k": FINAL_K,
        "passage_text": "full Stage 1 chunk text",
        "eval_file": str(eval_path),
        "eval_sha256": sha256_file(eval_path),
        "chunks_sha256": sha256_file(chunks_path),
        "hybrid_sha256": sha256_file(hybrid_path),
        "saved_hybrid_pool20_qwen_sha256": sha256_file(saved_qwen_path),
        "n_questions": len(alt_rows),
        "n_gold_reached_pool20": n_gold_in,
        "n_scores_reused": n_reused_used,
        "n_scores_new": n_new_used,
        "questions": alt_rows,
    }
    results_path.write_text(json.dumps(results_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    summary = {
        "reranker_model": MODEL_ID,
        "embedding_family": "qwen3_reranker_0_6b_local_alternating_pool20",
        "device": device,
        "device_reason": reason,
        "dtype": str(dtype).replace("torch.", ""),
        "batch_size": 2,
        "pool_k": POOL_K,
        "book_filter": "pride_and_prejudice",
        "n_gold_reached_pool20": n_gold_in,
        "frac_gold_reached_pool20": n_gold_in / len(alt_rows),
        "n_scores_reused": n_reused_used,
        "n_scores_new": n_new_used,
        "score_seconds_new_pairs_only": round(score_seconds, 3),
        "peak_rss_bytes": rss_bytes(),
        "peak_rss_gib": round(rss_bytes() / (1024**3), 3),
        "git_head": git_head(),
        "eval_sha256": sha256_file(eval_path),
        "results_file": str(results_path),
        "new_scores_file": str(new_scores_path),
        "overwrote_hybrid_pool20_baseline": False,
        **mets,
    }
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Pride alternating Hit@1/5/10 {mets['n_hit@1']}/{mets['n_hit@5']}/{mets['n_hit@10']} gold_in_20 {n_gold_in}/30")
    print(f"Wrote {results_path}")
    print(f"Wrote {summary_path}")

    write_four_book_comparison(
        compare_path,
        pride_alt_rows=alt_rows,
        pride_new_scores=new_scores,
        device=device,
    )
    return 0


def coverage_and_hits(*, gold_in: list[bool], ranks: list[int | None]) -> dict:
    n = len(ranks)
    n1 = sum(1 for r in ranks if hit_at(r, 1))
    n5 = sum(1 for r in ranks if hit_at(r, 5))
    n10 = sum(1 for r in ranks if hit_at(r, 10))
    return {
        "n_questions": n,
        "n_gold_reached_qwen": sum(1 for x in gold_in if x),
        "n_hit@1": n1,
        "n_hit@5": n5,
        "n_hit@10": n10,
        "mrr@10": sum(mrr_from_rank(r, 10) for r in ranks) / n if n else 0.0,
    }


def write_four_book_comparison(
    compare_path: Path,
    *,
    pride_alt_rows: list[dict],
    pride_new_scores: dict[str, dict[int, float]],
    device: str,
) -> None:
    books_out = []
    hybrid_fn = METHODS["hybrid_rrf_top20"]["fn"]
    alt_fn = METHODS[CHOSEN]["fn"]
    pride_alt_by_id = {r["id"]: r for r in pride_alt_rows}

    for spec in BOOKS:
        hybrid = json.loads(spec["hybrid"].read_text(encoding="utf-8"))
        scores_by_q = load_qwen_scores(spec["qwen"])
        rows = []
        for hq in hybrid["questions"]:
            qid = hq["id"]
            gold = set(int(i) for i in hq["gold_chunk_indexes"])
            dense_ids = ranked_ids(hq["dense_candidates"])
            sparse_ids = ranked_ids(hq["sparse_candidates"])
            hybrid_pool = hybrid_fn(dense_ids, sparse_ids)
            alt_pool = alt_fn(dense_ids, sparse_ids)
            scores = dict(scores_by_q.get(qid, {}))
            if spec["book_id"] == "pride_and_prejudice":
                scores.update(pride_new_scores.get(qid, {}))
            hy = simulate_rerank(hybrid_pool, scores, gold)
            al = simulate_rerank(alt_pool, scores, gold)
            if spec["book_id"] == "pride_and_prejudice" and not al["complete_saved_scores"]:
                raise RuntimeError(f"Pride {qid} still incomplete after new scores")
            if spec["book_id"] == "pride_and_prejudice":
                # prefer the live Pride ranking we just wrote
                live = pride_alt_by_id[qid]
                al = {
                    "complete_saved_scores": True,
                    "missing_chunk_indexes": [],
                    "first_gold_rank": live["first_gold_rank"],
                    "hit_at_1": live["hit_at_1"],
                    "hit_at_5": live["hit_at_5"],
                    "hit_at_10": live["hit_at_10"],
                }
            hy_in = gold_in_pool(hybrid_pool, gold)
            al_in = gold_in_pool(alt_pool, gold)
            rows.append(
                {
                    "id": qid,
                    "gold_reached_hybrid_pool20": hy_in,
                    "gold_reached_alternating_pool20": al_in,
                    "hybrid_first_gold_rank": hy["first_gold_rank"] if hy["complete_saved_scores"] else None,
                    "alternating_first_gold_rank": al["first_gold_rank"] if al["complete_saved_scores"] else None,
                    "hybrid_scores_complete": hy["complete_saved_scores"],
                    "alternating_scores_complete": al["complete_saved_scores"],
                    "changed": hy["first_gold_rank"] != al["first_gold_rank"]
                    if hy["complete_saved_scores"] and al["complete_saved_scores"]
                    else None,
                }
            )
        improved = [
            r["id"]
            for r in rows
            if r["hybrid_scores_complete"]
            and r["alternating_scores_complete"]
            and rank_key(r["alternating_first_gold_rank"]) < rank_key(r["hybrid_first_gold_rank"])
        ]
        worsened = [
            r["id"]
            for r in rows
            if r["hybrid_scores_complete"]
            and r["alternating_scores_complete"]
            and rank_key(r["alternating_first_gold_rank"]) > rank_key(r["hybrid_first_gold_rank"])
        ]
        gained_pool = [
            r["id"] for r in rows if r["gold_reached_alternating_pool20"] and not r["gold_reached_hybrid_pool20"]
        ]
        lost_pool = [
            r["id"] for r in rows if r["gold_reached_hybrid_pool20"] and not r["gold_reached_alternating_pool20"]
        ]
        hybrid_metrics = coverage_and_hits(
            gold_in=[r["gold_reached_hybrid_pool20"] for r in rows],
            ranks=[r["hybrid_first_gold_rank"] if r["hybrid_scores_complete"] else None for r in rows],
        )
        alt_metrics = coverage_and_hits(
            gold_in=[r["gold_reached_alternating_pool20"] for r in rows],
            ranks=[r["alternating_first_gold_rank"] if r["alternating_scores_complete"] else None for r in rows],
        )

        books_out.append(
            {
                "book_id": spec["book_id"],
                "score_source": spec["qwen"].name
                if spec["book_id"] != "pride_and_prejudice"
                else "saved hybrid-pool20 scores + new alternating-only scores",
                "hybrid_pool20": hybrid_metrics,
                "alternating_pool20": alt_metrics,
                "pool_gained_ids": gained_pool,
                "pool_lost_ids": lost_pool,
                "rerank_improved_ids": improved,
                "rerank_worsened_ids": worsened,
                "questions": rows,
            }
        )

    payload = {
        "experiment": "qwen_alternating_vs_hybrid_pool20_four_books",
        "chosen_pool_rule": CHOSEN,
        "chosen_label": METHODS[CHOSEN]["label"],
        "device": device,
        "did_not_overwrite_baselines": True,
        "did_not_edit_frozen_questions": True,
        "books": books_out,
    }
    compare_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {compare_path}")
    print("\nFour-book comparison (gold reached 20 / Hit@1 / Hit@5 / Hit@10)")
    for b in books_out:
        h = b["hybrid_pool20"]
        a = b["alternating_pool20"]
        print(
            f"{b['book_id']:22} hybrid {h['n_gold_reached_qwen']:2d} {h['n_hit@1']:2d}/{h['n_hit@5']:2d}/{h['n_hit@10']:2d}"
            f"  alt {a['n_gold_reached_qwen']:2d} {a['n_hit@1']:2d}/{a['n_hit@5']:2d}/{a['n_hit@10']:2d}"
            f"  pool +{b['pool_gained_ids']} -{b['pool_lost_ids']}"
            f"  rank +{b['rerank_improved_ids']} -{b['rerank_worsened_ids']}"
        )


if __name__ == "__main__":
    sys.exit(main())
