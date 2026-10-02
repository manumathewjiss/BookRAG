"""
Offline fusion comparison on saved BGE-M3 dense/sparse candidate lists.

Does not load embedding models, re-chunk PDFs, or overwrite prior result files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from bge_m3_sparse import reciprocal_rank_fusion
from evaluate_retrieval_stage3 import first_gold_rank, hit_at, mrr_from_rank

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "outputs"
RRF_K = 60
FINAL_K = 10
BOOKS = ("thinkpython", "arthashastra", "bhagavad_gita")
FOCUS = ("bg_010", "bg_025")

# Fixed before looking at method scores:
# 1) smaller best rank wins
# 2) a passage on both lists beats a passage on one list
# 3) smaller chunk_index wins (same stable rule as current RRF)
BEST_POSITION_TIE_BREAK = (
    "min(dense_rank, sparse_rank); then prefer appearing in both lists; then smaller chunk_index"
)

DIRECTORY_RE = re.compile(
    r"(p\.o\.\s*box|pamho\.net|hare krishna land|cairo rd|"
    r"tel\.\s*\+?\d|fax:\s*\(|iskcon\.[a-z]|bharatpuri|"
    r"kisumu|ujjain, mp|lome, togo)",
    re.I,
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rank_key(rank: int | None) -> int:
    return 11 if rank is None else rank


def looks_like_address_directory(preview: str) -> bool:
    return bool(DIRECTORY_RE.search(preview or ""))


def candidate_map(hits: list[dict]) -> dict[int, dict]:
    out: dict[int, dict] = {}
    for h in hits:
        out[int(h["chunk_index"])] = h
    return out


def ranking_ids(hits: list[dict]) -> list[int]:
    return [int(h["chunk_index"]) for h in hits]


def fuse_weighted_rrf(
    dense_ids: list[int],
    sparse_ids: list[int],
    *,
    rrf_k: int = RRF_K,
    dense_weight: float = 2.0,
    sparse_weight: float = 1.0,
    top_k: int = FINAL_K,
) -> list[dict[str, Any]]:
    scores: dict[int, float] = defaultdict(float)
    sources: dict[int, dict[str, int | None]] = {}
    for rank, cid in enumerate(dense_ids, start=1):
        scores[cid] += dense_weight / (rrf_k + rank)
        sources.setdefault(cid, {"dense_rank": None, "sparse_rank": None})["dense_rank"] = rank
    for rank, cid in enumerate(sparse_ids, start=1):
        scores[cid] += sparse_weight / (rrf_k + rank)
        sources.setdefault(cid, {"dense_rank": None, "sparse_rank": None})["sparse_rank"] = rank
    fused = sorted(scores.items(), key=lambda item: (-item[1], item[0]))[:top_k]
    out = []
    for rank, (cid, score) in enumerate(fused, start=1):
        rec = sources[cid]
        out.append(
            {
                "rank": rank,
                "chunk_index": cid,
                "score": float(score),
                "dense_rank": rec["dense_rank"],
                "sparse_rank": rec["sparse_rank"],
            }
        )
    return out


def fuse_best_position(
    dense_ids: list[int],
    sparse_ids: list[int],
    *,
    top_k: int = FINAL_K,
) -> list[dict[str, Any]]:
    dense_pos = {cid: rank for rank, cid in enumerate(dense_ids, start=1)}
    sparse_pos = {cid: rank for rank, cid in enumerate(sparse_ids, start=1)}
    all_ids = set(dense_pos) | set(sparse_pos)
    rows = []
    for cid in all_ids:
        d = dense_pos.get(cid)
        s = sparse_pos.get(cid)
        best = min(x for x in (d, s) if x is not None)
        n_lists = int(d is not None) + int(s is not None)
        rows.append((best, -n_lists, cid, d, s))
    rows.sort()
    out = []
    for rank, (best, neg_n, cid, d, s) in enumerate(rows[:top_k], start=1):
        out.append(
            {
                "rank": rank,
                "chunk_index": cid,
                "best_rank": best,
                "n_lists": -neg_n,
                "dense_rank": d,
                "sparse_rank": s,
            }
        )
    return out


def attach_previews(fused: list[dict], dense_map: dict[int, dict], sparse_map: dict[int, dict]) -> list[dict]:
    out = []
    for item in fused:
        cid = item["chunk_index"]
        src = dense_map.get(cid) or sparse_map.get(cid) or {}
        preview = src.get("text_preview", "")
        out.append(
            {
                **item,
                "page": src.get("page"),
                "text_preview": preview,
                "is_address_directory": looks_like_address_directory(preview),
            }
        )
    return out


def metrics_from_ranks(ranks: list[int | None]) -> dict:
    n = len(ranks)
    n1 = sum(1 for r in ranks if hit_at(r, 1))
    n5 = sum(1 for r in ranks if hit_at(r, 5))
    n10 = sum(1 for r in ranks if hit_at(r, 10))
    return {
        "n_questions": n,
        "n_hit@1": n1,
        "n_hit@5": n5,
        "n_hit@10": n10,
        "hit@1": n1 / n if n else 0.0,
        "hit@5": n5 / n if n else 0.0,
        "hit@10": n10 / n if n else 0.0,
        "mrr@10": sum(mrr_from_rank(r, 10) for r in ranks) / n if n else 0.0,
        "n_misses_top10": n - n10,
    }


def deltas_vs_rrf(rrf_ranks: dict[str, int | None], other_ranks: dict[str, int | None]) -> dict:
    improved = worsened = unchanged = 0
    improved_ids: list[str] = []
    worsened_ids: list[str] = []
    for qid in rrf_ranks:
        old, new = rrf_ranks[qid], other_ranks[qid]
        if rank_key(new) < rank_key(old):
            improved += 1
            improved_ids.append(qid)
        elif rank_key(new) > rank_key(old):
            worsened += 1
            worsened_ids.append(qid)
        else:
            unchanged += 1
    return {
        "n_improved": improved,
        "n_worsened": worsened,
        "n_unchanged": unchanged,
        "improved_ids": improved_ids,
        "worsened_ids": worsened_ids,
    }


def process_book(book_id: str) -> tuple[dict, dict]:
    hybrid_path = OUTPUT_DIR / f"{book_id}_bge_m3_hybrid_retrieval_results_30.json"
    payload = json.loads(hybrid_path.read_text(encoding="utf-8"))
    questions_out = []
    rrf_ranks: dict[str, int | None] = {}
    best_ranks: dict[str, int | None] = {}
    wrrf_ranks: dict[str, int | None] = {}
    reproduce_ok = True
    mismatches = []

    for q in payload["questions"]:
        gold = set(int(i) for i in q["gold_chunk_indexes"])
        dense = q["dense_candidates"]
        sparse = q["sparse_candidates"]
        dense_ids = ranking_ids(dense)
        sparse_ids = ranking_ids(sparse)
        dense_map = candidate_map(dense)
        sparse_map = candidate_map(sparse)

        rrf = attach_previews(
            reciprocal_rank_fusion([dense_ids, sparse_ids], rrf_k=RRF_K, top_k=FINAL_K),
            dense_map,
            sparse_map,
        )
        saved = [int(h["chunk_index"]) for h in q["retrieved"][:FINAL_K]]
        replay = [h["chunk_index"] for h in rrf]
        if saved != replay:
            reproduce_ok = False
            mismatches.append({"id": q["id"], "saved": saved, "replay": replay})

        best = attach_previews(fuse_best_position(dense_ids, sparse_ids), dense_map, sparse_map)
        wrrf = attach_previews(
            fuse_weighted_rrf(dense_ids, sparse_ids, dense_weight=2.0, sparse_weight=1.0),
            dense_map,
            sparse_map,
        )

        rrf_rank = first_gold_rank([h["chunk_index"] for h in rrf], gold)
        best_rank = first_gold_rank([h["chunk_index"] for h in best], gold)
        wrrf_rank = first_gold_rank([h["chunk_index"] for h in wrrf], gold)
        rrf_ranks[q["id"]] = rrf_rank
        best_ranks[q["id"]] = best_rank
        wrrf_ranks[q["id"]] = wrrf_rank

        questions_out.append(
            {
                "id": q["id"],
                "question": q["question"],
                "gold_chunk_indexes": sorted(gold),
                "rrf_first_gold_rank": rrf_rank,
                "best_position_first_gold_rank": best_rank,
                "dense_weighted_rrf_first_gold_rank": wrrf_rank,
                "methods": {
                    "rrf": rrf,
                    "best_position": best,
                    "dense_weighted_rrf": wrrf,
                },
            }
        )

    method_metrics = {
        "rrf": metrics_from_ranks(list(rrf_ranks.values())),
        "best_position": metrics_from_ranks(list(best_ranks.values())),
        "dense_weighted_rrf": metrics_from_ranks(list(wrrf_ranks.values())),
    }
    vs_rrf = {
        "best_position": deltas_vs_rrf(rrf_ranks, best_ranks),
        "dense_weighted_rrf": deltas_vs_rrf(rrf_ranks, wrrf_ranks),
    }

    directory_counts = {}
    for name in ("rrf", "best_position", "dense_weighted_rrf"):
        n_q = 0
        n_hits = 0
        by_q = {}
        for q in questions_out:
            dirs = [h for h in q["methods"][name] if h["is_address_directory"]]
            if dirs:
                n_q += 1
                n_hits += len(dirs)
                by_q[q["id"]] = [
                    {"rank": h["rank"], "chunk_index": h["chunk_index"], "text_preview": h["text_preview"][:120]}
                    for h in dirs
                ]
        directory_counts[name] = {
            "n_questions_with_directory_in_top10": n_q,
            "n_directory_hits_in_top10": n_hits,
            "questions": by_q,
        }

    focus = {}
    for qid in FOCUS:
        row = next((x for x in questions_out if x["id"] == qid), None)
        if row:
            focus[qid] = {
                "question": row["question"],
                "gold_chunk_indexes": row["gold_chunk_indexes"],
                "rrf": row["rrf_first_gold_rank"],
                "best_position": row["best_position_first_gold_rank"],
                "dense_weighted_rrf": row["dense_weighted_rrf_first_gold_rank"],
                "top10": {
                    m: [
                        {
                            "rank": h["rank"],
                            "chunk_index": h["chunk_index"],
                            "dense_rank": h.get("dense_rank"),
                            "sparse_rank": h.get("sparse_rank"),
                            "is_address_directory": h["is_address_directory"],
                            "text_preview": h["text_preview"][:180],
                        }
                        for h in row["methods"][m]
                    ]
                    for m in ("rrf", "best_position", "dense_weighted_rrf")
                },
            }

    book_report = {
        "book_id": book_id,
        "source_hybrid_file": str(hybrid_path),
        "source_hybrid_sha256": sha256_file(hybrid_path),
        "rrf_reproduction_matches_saved_hybrid": reproduce_ok,
        "rrf_reproduction_mismatches": mismatches,
        "best_position_tie_break": BEST_POSITION_TIE_BREAK,
        "dense_weighted_rrf": {"rrf_k": RRF_K, "dense_weight": 2.0, "sparse_weight": 1.0},
        "metrics": method_metrics,
        "vs_current_rrf": vs_rrf,
        "address_directory_in_top10": directory_counts,
        "focus_questions": focus,
        "questions": [
            {
                "id": q["id"],
                "question": q["question"],
                "gold_chunk_indexes": q["gold_chunk_indexes"],
                "rrf_first_gold_rank": q["rrf_first_gold_rank"],
                "best_position_first_gold_rank": q["best_position_first_gold_rank"],
                "dense_weighted_rrf_first_gold_rank": q["dense_weighted_rrf_first_gold_rank"],
                "rrf_top10": [
                    {"rank": h["rank"], "chunk_index": h["chunk_index"], "is_address_directory": h["is_address_directory"]}
                    for h in q["methods"]["rrf"]
                ],
                "best_position_top10": [
                    {
                        "rank": h["rank"],
                        "chunk_index": h["chunk_index"],
                        "best_rank": h.get("best_rank"),
                        "dense_rank": h.get("dense_rank"),
                        "sparse_rank": h.get("sparse_rank"),
                        "is_address_directory": h["is_address_directory"],
                    }
                    for h in q["methods"]["best_position"]
                ],
                "dense_weighted_rrf_top10": [
                    {
                        "rank": h["rank"],
                        "chunk_index": h["chunk_index"],
                        "dense_rank": h.get("dense_rank"),
                        "sparse_rank": h.get("sparse_rank"),
                        "is_address_directory": h["is_address_directory"],
                    }
                    for h in q["methods"]["dense_weighted_rrf"]
                ],
            }
            for q in questions_out
        ],
    }
    detailed = {
        "book_id": book_id,
        "embedding_family": "bge_m3_fusion_offline",
        "n_questions": len(questions_out),
        "questions": questions_out,
    }
    return book_report, detailed


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Offline comparison of fusion methods on saved candidates.")
    p.add_argument("--out", type=Path, default=OUTPUT_DIR / "bge_m3_fusion_offline_comparison.json")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    books = []
    for book_id in BOOKS:
        report, detailed = process_book(book_id)
        books.append(report)
        detail_path = OUTPUT_DIR / f"{book_id}_bge_m3_fusion_offline_results_30.json"
        detail_path.write_text(json.dumps(detailed, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Wrote {detail_path} rrf_ok={report['rrf_reproduction_matches_saved_hybrid']}")

    payload = {
        "experiment": "bge_m3_fusion_offline_saved_candidates",
        "note": "No new embeddings. Candidates copied from existing bge_m3_hybrid results.",
        "methods": [
            "rrf k=60 equal weights (reproduction)",
            "best_position",
            "dense_weighted_rrf dense=2 sparse=1 k=60",
        ],
        "books": books,
    }
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {args.out}")
    for book in books:
        print(f"\n{book['book_id']}")
        for name, m in book["metrics"].items():
            print(
                f"  {name}: @{1}/{5}/{10} = {m['n_hit@1']}/{m['n_hit@5']}/{m['n_hit@10']} "
                f"MRR={m['mrr@10']:.3f} dir_q={book['address_directory_in_top10'][name]['n_questions_with_directory_in_top10']}"
            )
        for name, d in book["vs_current_rrf"].items():
            print(f"  vs RRF {name}: imp={d['improved_ids']} worse={d['worsened_ids']}")
    return 0 if all(b["rrf_reproduction_matches_saved_hybrid"] for b in books) else 1


if __name__ == "__main__":
    raise SystemExit(main())
