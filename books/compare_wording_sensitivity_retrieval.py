"""
Compare baseline hybrid top-20 vs dual-query merge on frozen wording cases.

Preserves baseline as a separate method. Does not overwrite earlier result files.
Gold passage IDs are never sent to Sol.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "demo") not in sys.path:
    sys.path.insert(0, str(ROOT / "demo"))

from demo_retrieval_helpers import (
    clean_display_excerpt,
    one_alternative_phrasing,
    quoted_spans_supported_by_citations,
)
from local_env import load_local_env, openai_api_key_configured
from pipeline import CANDIDATE_K, HYBRID_K, QWEN_TOP, RRF_K, DemoEngine
from bge_m3_sparse import reciprocal_rank_fusion, search_sparse
from db import connect, search_chunks_bge_m3
from evaluate_bge_m3_dense import embed_query
from sol_answer_common import (
    ANSWER_SCHEMA_WITH_ANSWER_SUPPORT,
    ANSWER_SUPPORT_INSTRUCTIONS,
    MODEL,
    REASONING_EFFORT,
    SERVICE_TIER,
    apply_event_match_gate,
    estimate_usd,
    reader_evidence_label,
    redact,
    sanitize_citations,
)

CASES = ROOT / "outputs" / "sol_wording_sensitivity_cases.json"
OUT = ROOT / "outputs" / "sol_wording_sensitivity_results.json"
SUMMARY = ROOT / "outputs" / "sol_wording_sensitivity_summary.json"
REVIEW = ROOT / "outputs" / "sol_wording_sensitivity_review.json"
STOP_USD = 18.0


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def gold_rank(ids: list[int], golds: list[int]) -> int | None:
    for g in golds:
        if g in ids:
            return ids.index(g) + 1
    return None


def hybrid_once(engine: DemoEngine, book_id: str, question: str, *, top_k: int = HYBRID_K) -> tuple[list[dict], float]:
    pack = engine._load_book(book_id)
    t0 = time.perf_counter()
    qvec, _ = embed_query(engine.dense, question, device="cpu")
    q_sparse = engine.sparse_encoder.encode_lexical_weights([question], batch_size=1)[0]
    conn = connect()
    try:
        dense_hits = search_chunks_bge_m3(conn, book_id=book_id, query_embedding=qvec.tolist(), top_k=CANDIDATE_K)
    finally:
        conn.close()
    sparse_hits = search_sparse(query_weights=q_sparse, corpus=pack["corpus"], index=pack["index"], top_k=CANDIDATE_K)
    fused = reciprocal_rank_fusion(
        [[h["chunk_index"] for h in dense_hits], [h["chunk_index"] for h in sparse_hits]],
        rrf_k=RRF_K,
        top_k=top_k,
    )
    hybrid = []
    for item in fused:
        row = pack["by_id"][item["chunk_index"]]
        hybrid.append(
            {
                "passage_id": int(item["chunk_index"]),
                "page": row.get("page"),
                "text": row["text"],
                "rrf_rank": item["rank"],
                "dense_rank": item.get("dense_rank"),
                "sparse_rank": item.get("sparse_rank"),
            }
        )
    return hybrid, time.perf_counter() - t0


def retrieve(engine: DemoEngine, book_id: str, question: str, method: str) -> dict:
    alt = one_alternative_phrasing(question) if method == "dual_query_merge_hybrid20_qwen5" else None
    if method == "baseline_hybrid20_qwen5" or not alt:
        hybrid, retrieve_s = hybrid_once(engine, book_id, question, top_k=HYBRID_K)
        queries_used = [question]
        alt_used = None
        if method.startswith("dual") and not alt:
            # Dual requested but no alt: identical to baseline (honest accounting)
            pass
    else:
        h1, t1 = hybrid_once(engine, book_id, question, top_k=HYBRID_K)
        h2, t2 = hybrid_once(engine, book_id, alt, top_k=HYBRID_K)
        fused = reciprocal_rank_fusion(
            [[h["passage_id"] for h in h1], [h["passage_id"] for h in h2]],
            rrf_k=RRF_K,
            top_k=HYBRID_K,
        )
        pack = engine._load_book(book_id)
        hybrid = []
        for item in fused:
            row = pack["by_id"][item["chunk_index"]]
            hybrid.append(
                {
                    "passage_id": int(item["chunk_index"]),
                    "page": row.get("page"),
                    "text": row["text"],
                    "rrf_rank": item["rank"],
                }
            )
        retrieve_s = t1 + t2
        queries_used = [question, alt]
        alt_used = alt

    t1 = time.perf_counter()
    scores = engine.qwen.score_pairs(question, [h["text"] for h in hybrid], batch_size=2)
    ranked = sorted(zip(hybrid, scores), key=lambda x: (-x[1], x[0]["passage_id"]))
    top = []
    for rec, sc in ranked[:QWEN_TOP]:
        item = dict(rec)
        item["qwen_score"] = float(sc)
        top.append(item)
    qwen_s = time.perf_counter() - t1
    return {
        "method": method,
        "alternative_phrasing": alt_used,
        "queries_used": queries_used,
        "hybrid": hybrid,
        "top": top,
        "retrieve_s": retrieve_s,
        "qwen_s": qwen_s,
    }


def call_sol(engine: DemoEngine, question: str, top: list[dict]) -> dict:
    passage_block = "\n\n".join(f"[passage_id={p['passage_id']}]\n{p['text']}" for p in top)
    user_msg = f"Question:\n{question}\n\nPassages (use only these; cite passage_id values):\n{passage_block}"
    t0 = time.perf_counter()
    resp = engine.client.responses.create(
        model=MODEL,
        service_tier=SERVICE_TIER,
        store=False,
        reasoning={"effort": REASONING_EFFORT},
        instructions=ANSWER_SUPPORT_INSTRUCTIONS,
        input=user_msg,
        text={
            "format": {
                "type": "json_schema",
                "name": "bookrag_grounded_answer_support",
                "strict": True,
                "schema": ANSWER_SCHEMA_WITH_ANSWER_SUPPORT,
            }
        },
    )
    sol_s = time.perf_counter() - t0
    parsed = apply_event_match_gate(json.loads((resp.output_text or "").strip()))
    usage = resp.usage.model_dump() if hasattr(resp.usage, "model_dump") else {}
    sent = [{"passage_id": p["passage_id"], "page": p["page"], "text": p["text"]} for p in top]
    gate = sanitize_citations([int(i) for i in parsed.get("supporting_passage_ids") or []], sent)
    by_id = {p["passage_id"]: p for p in top}
    supporting = []
    for c in gate["display_citations"]:
        rec = by_id[c["passage_id"]]
        supporting.append({"passage_id": c["passage_id"], "page": c["page"], "text": rec["text"]})
    enough = bool(parsed.get("enough_evidence")) and bool(supporting)
    quote_check = quoted_spans_supported_by_citations(
        parsed.get("answer") or "",
        [p["text"] for p in supporting],
    )
    return {
        "answer": parsed.get("answer"),
        "enough_evidence": enough,
        "evidence_label": reader_evidence_label(str(parsed.get("event_match") or ""), enough, len(supporting)),
        "event_match": parsed.get("event_match"),
        "asked_event": parsed.get("asked_event"),
        "missing_evidence": parsed.get("missing_evidence") or "",
        "citations": gate["display_citations"],
        "supporting_passage_ids": gate["accepted_passage_ids"],
        "quote_check": quote_check,
        "api_time_seconds": round(sol_s, 3),
        "cost": estimate_usd(usage if isinstance(usage, dict) else {}),
        "response_id": getattr(resp, "id", None),
        "display_excerpt_sample": [
            {
                "passage_id": p["passage_id"],
                "page": p["page"],
                "excerpt": clean_display_excerpt(p["text"]),
            }
            for p in supporting[:2]
        ],
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--cases", type=Path, default=CASES)
    p.add_argument("--out", type=Path, default=OUT)
    p.add_argument("--summary", type=Path, default=SUMMARY)
    p.add_argument("--review", type=Path, default=REVIEW)
    p.add_argument("--stop-usd", type=float, default=STOP_USD)
    p.add_argument("--retrieval-only", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if args.out.exists() or args.summary.exists():
        print("Refusing to overwrite wording-sensitivity result files.")
        return 2
    spec = json.loads(args.cases.read_text(encoding="utf-8"))
    if not spec.get("frozen_before_search_change"):
        print("Cases not frozen.")
        return 2
    load_local_env()
    if not args.retrieval_only and not openai_api_key_configured():
        print("OPENAI_API_KEY missing from books/.env")
        return 2

    engine = DemoEngine()
    spent = float(spec.get("already_tracked_sol_usd") or 1.398)
    rows = []
    stopped = None
    methods = list(spec["methods_to_compare"])

    for case in spec["cases"]:
        row = {
            "id": case["id"],
            "question_id": case.get("question_id"),
            "book": case["book"],
            "book_id": case["book_id"],
            "question": case["question"],
            "role": case["role"],
            "expects_answerable": case["expects_answerable"],
            "gold_passage_ids": case["gold_passage_ids"],
            "methods": {},
        }
        for method in methods:
            if spent >= args.stop_usd:
                stopped = f"stop_usd before {case['id']} {method}"
                break
            t_all = time.perf_counter()
            retrieved = retrieve(engine, case["book_id"], case["question"], method)
            hybrid_ids = [h["passage_id"] for h in retrieved["hybrid"]]
            sol5_ids = [p["passage_id"] for p in retrieved["top"]]
            golds = list(case["gold_passage_ids"] or [])
            # Initial search = candidate pool before final hybrid cut is not fully exposed;
            # report dense/sparse via hybrid membership and ranks within the 20.
            gold_in_hybrid20 = any(g in hybrid_ids for g in golds) if golds else None
            gold_in_sol5 = any(g in sol5_ids for g in golds) if golds else None
            method_row = {
                "alternative_phrasing": retrieved["alternative_phrasing"],
                "queries_used": retrieved["queries_used"],
                "hybrid_pool20_ids": hybrid_ids,
                "qwen_top5_ids": sol5_ids,
                "gold_rank_in_hybrid20": gold_rank(hybrid_ids, golds) if golds else None,
                "gold_rank_in_sol5": gold_rank(sol5_ids, golds) if golds else None,
                "correct_passage_in_hybrid20": gold_in_hybrid20,
                "correct_passage_in_sol5": gold_in_sol5,
                "timings_seconds": {
                    "retrieve_hybrid": round(retrieved["retrieve_s"], 3),
                    "qwen_rerank": round(retrieved["qwen_s"], 3),
                },
            }
            if not args.retrieval_only:
                try:
                    sol = call_sol(engine, case["question"], retrieved["top"])
                except Exception as exc:
                    print(redact(str(exc)))
                    stopped = "api_error"
                    break
                spent += float(sol["cost"]["estimated_usd"])
                method_row["sol"] = sol
                method_row["timings_seconds"]["sol_api"] = sol["api_time_seconds"]
                method_row["timings_seconds"]["total_wait"] = round(time.perf_counter() - t_all, 3)
                # Separate judgments (manual review fills answer_correct; code fills passage/citation checks)
                cited = sol["supporting_passage_ids"]
                method_row["judgments"] = {
                    "correct_passage_found_in_sol5": gold_in_sol5,
                    "gold_cited": (any(g in cited for g in golds) if golds else None),
                    "enough_evidence_flag": sol["enough_evidence"],
                    "quote_words_in_cited_passage": sol["quote_check"]["all_supported"],
                    "expects_answerable": case["expects_answerable"],
                }
                print(
                    f"{case['id']} {method} hybrid_gold={method_row['gold_rank_in_hybrid20']} "
                    f"sol5_gold={method_row['gold_rank_in_sol5']} enough={sol['enough_evidence']} "
                    f"quotes_ok={sol['quote_check']['all_supported']} "
                    f"${sol['cost']['estimated_usd']:.4f} total=${spent:.4f} "
                    f"wait={method_row['timings_seconds']['total_wait']:.1f}s"
                )
            else:
                method_row["timings_seconds"]["total_wait"] = round(time.perf_counter() - t_all, 3)
                print(
                    f"{case['id']} {method} hybrid_gold={method_row['gold_rank_in_hybrid20']} "
                    f"sol5_gold={method_row['gold_rank_in_sol5']} "
                    f"wait={method_row['timings_seconds']['total_wait']:.1f}s"
                )
            row["methods"][method] = method_row
        rows.append(row)
        if stopped:
            break

    payload = {
        "experiment": "sol_wording_sensitivity_baseline_vs_dual_query",
        "production_pipeline_changed": False,
        "live_demo_search_changed": False,
        "cases_file": str(args.cases),
        "cases_sha256": sha256_file(args.cases),
        "already_tracked_sol_usd": spec.get("already_tracked_sol_usd") or 1.398,
        "estimated_usd_total_including_prior": round(spent, 6),
        "estimated_usd_this_run": round(spent - float(spec.get("already_tracked_sol_usd") or 1.398), 6),
        "n_questions_planned": spec["n_questions"],
        "n_questions_run": len(rows),
        "stopped": stopped,
        "gold_ids_sent_to_sol": False,
        "questions": rows,
    }
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # Aggregate for summary
    base = "baseline_hybrid20_qwen5"
    dual = "dual_query_merge_hybrid20_qwen5"
    answerable = [r for r in rows if r["expects_answerable"] and golds_ok(r)]
    unans = [r for r in rows if not r["expects_answerable"]]

    def count_sol5(method: str) -> int:
        return sum(
            1
            for r in answerable
            if r["methods"].get(method, {}).get("correct_passage_in_sol5")
        )

    def mean_wait(method: str) -> float | None:
        waits = [
            r["methods"][method]["timings_seconds"].get("total_wait")
            for r in rows
            if method in r["methods"] and r["methods"][method]["timings_seconds"].get("total_wait") is not None
        ]
        return round(sum(waits) / len(waits), 3) if waits else None

    summary = {
        "n_questions_run": len(rows),
        "answerable_with_gold": len(answerable),
        "baseline_gold_in_sol5": count_sol5(base),
        "dual_gold_in_sol5": count_sol5(dual),
        "baseline_mean_total_wait_s": mean_wait(base),
        "dual_mean_total_wait_s": mean_wait(dual),
        "estimated_usd_this_run": payload["estimated_usd_this_run"],
        "estimated_usd_total_including_prior": payload["estimated_usd_total_including_prior"],
        "stopped": stopped,
        "results_file": str(args.out),
        "unanswerable_n": len(unans),
    }
    args.summary.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print("Wrote", args.out)
    print("Wrote", args.summary)
    return 0


def golds_ok(row: dict) -> bool:
    return bool(row.get("gold_passage_ids"))


if __name__ == "__main__":
    raise SystemExit(main())
