"""
End-to-end rehearsal for professor-demo books on fixed cases.

Reuses existing DB indexes. Does not overwrite earlier baselines.
Gold IDs are not sent to Sol.
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

import pipeline as demo_pipeline
from demo_retrieval_helpers import quoted_spans_supported_by_citations
from local_env import load_local_env, openai_api_key_configured

CASES = ROOT / "outputs" / "professor_demo_rehearsal_cases.json"
OUT = ROOT / "outputs" / "professor_demo_rehearsal_results.json"
SUMMARY = ROOT / "outputs" / "professor_demo_rehearsal_summary.json"
REVIEW = ROOT / "outputs" / "professor_demo_rehearsal_review.json"

EXTRA_BOOKS = {
    "bhagavad_gita": {
        "label": "Bhagavad-gītā As It Is",
        "chunks": ROOT / "outputs" / "bhagavad_gita_stage1_chunks.json",
    },
    "arthashastra": {
        "label": "Arthashastra (Temple Library excerpt)",
        "chunks": ROOT / "outputs" / "arthashastra_stage1_chunks.json",
    },
}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def failure_locus(gold_ids: list[int], hybrid_ids: list[int], sol5_ids: list[int], cited: list[int], enough: bool, expects: bool) -> str | None:
    if not expects:
        if enough:
            return "sol_overconfident"
        return None
    if not gold_ids:
        return None
    gold_in_hybrid = any(g in hybrid_ids for g in gold_ids)
    gold_in_sol5 = any(g in sol5_ids for g in gold_ids)
    gold_cited = any(g in cited for g in gold_ids)
    if not gold_in_hybrid:
        return "search_missed_gold"
    if not gold_in_sol5:
        return "qwen_dropped_gold"
    if not enough:
        return "sol_refused_despite_gold_in_sol5"
    if not gold_cited:
        return "sol_cited_other_than_gold"
    return None


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--cases", type=Path, default=CASES)
    p.add_argument("--out", type=Path, default=OUT)
    p.add_argument("--summary", type=Path, default=SUMMARY)
    p.add_argument("--review", type=Path, default=REVIEW)
    p.add_argument("--stop-usd", type=float, default=18.0)
    args = p.parse_args()
    if args.out.exists() or args.summary.exists():
        print("Refusing to overwrite professor rehearsal result files.")
        return 2
    spec = json.loads(args.cases.read_text(encoding="utf-8"))
    if not spec.get("frozen_before_api_calls"):
        print("Cases not frozen.")
        return 2
    load_local_env()
    if not openai_api_key_configured():
        print("OPENAI_API_KEY missing from gitignored books/.env")
        return 2

    # Temporarily register professor books for this rehearsal without editing picker yet.
    demo_pipeline.BOOKS = {**demo_pipeline.BOOKS, **EXTRA_BOOKS}
    # Load only the three presentation books to keep startup lighter.
    only = {"bhagavad_gita", "arthashastra", "thinkpython"}
    demo_pipeline.BOOKS = {k: v for k, v in demo_pipeline.BOOKS.items() if k in only}

    engine = demo_pipeline.DemoEngine()
    spent = float(spec.get("already_tracked_sol_usd") or 1.527)
    rows = []
    stopped = None

    for case in spec["cases"]:
        if spent >= args.stop_usd:
            stopped = f"stop_usd before {case['id']}"
            break
        t0 = time.perf_counter()
        try:
            result = engine.ask(case["book_id"], case["question"])
        except Exception as exc:
            print(str(exc)[:300])
            stopped = "api_or_pipeline_error"
            break
        client_wait = time.perf_counter() - t0
        cost = float((result.get("cost") or {}).get("estimated_usd") or 0)
        spent += cost
        golds = list(case.get("gold_passage_ids") or [])
        hybrid = list(result.get("hybrid_pool20_ids") or [])
        sol5 = list(result.get("qwen_top5_ids") or [])
        cited = [c["passage_id"] for c in (result.get("citations") or [])]
        quote_check = quoted_spans_supported_by_citations(
            result.get("answer") or "",
            [p.get("text") or "" for p in (result.get("supporting_passages") or [])],
        )
        locus = failure_locus(
            golds,
            hybrid,
            sol5,
            cited,
            bool(result.get("enough_evidence")),
            bool(case["expects_answerable"]),
        )
        row = {
            "id": case["id"],
            "book_id": case["book_id"],
            "role": case["role"],
            "question": case["question"],
            "expects_answerable": case["expects_answerable"],
            "gold_passage_ids": golds,
            "expected_pdf_pages": case.get("expected_pdf_pages"),
            "enough_evidence": result.get("enough_evidence"),
            "evidence_label": result.get("evidence_label"),
            "event_match": result.get("event_match"),
            "answer": result.get("answer"),
            "citations": result.get("citations"),
            "supporting_excerpts": [
                {
                    "passage_id": p["passage_id"],
                    "page": p["page"],
                    "excerpt": p.get("excerpt"),
                }
                for p in (result.get("supporting_passages") or [])
            ],
            "hybrid_pool20_ids": hybrid,
            "qwen_top5_ids": sol5,
            "gold_in_hybrid20": (any(g in hybrid for g in golds) if golds else None),
            "gold_in_sol5": (any(g in sol5 for g in golds) if golds else None),
            "gold_cited": (any(g in cited for g in golds) if golds else None),
            "quote_check": {
                "all_supported": quote_check["all_supported"],
                "asks_or_uses_quotes": quote_check["asks_or_uses_quotes"],
                "unsupported": quote_check.get("unsupported"),
            },
            "failure_locus": locus,
            "timings_seconds": result.get("timings_seconds"),
            "client_wait_s": round(client_wait, 3),
            "cost_estimated_usd": cost,
        }
        rows.append(row)
        print(
            f"{case['id']} enough={result.get('enough_evidence')} gold_hybrid={row['gold_in_hybrid20']} "
            f"gold_sol5={row['gold_in_sol5']} gold_cited={row['gold_cited']} locus={locus} "
            f"wait={row['timings_seconds']['total_wait']}s ${cost:.4f} total=${spent:.4f}"
        )
        print(" ", (result.get("answer") or "")[:220].replace("\n", " "))

    payload = {
        "experiment": "professor_demo_rehearsal_e2e",
        "production_pipeline_changed": False,
        "cases_file": str(args.cases),
        "cases_sha256": sha256_file(args.cases),
        "already_tracked_sol_usd": spec.get("already_tracked_sol_usd"),
        "estimated_usd_this_run": round(spent - float(spec.get("already_tracked_sol_usd") or 0), 6),
        "estimated_usd_total_including_prior": round(spent, 6),
        "n_questions_planned": spec["n_questions"],
        "n_questions_run": len(rows),
        "stopped": stopped,
        "startup_seconds": getattr(engine, "startup_seconds", None),
        "org_costs_api": "not_queried_this_run; prior sessions lacked api.usage.read",
        "gold_ids_sent_to_sol": False,
        "questions": rows,
    }
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    fails = [r for r in rows if r["failure_locus"] or (r["expects_answerable"] and not r["enough_evidence"]) or ((not r["expects_answerable"]) and r["enough_evidence"])]
    review = {
        "artifact": "professor_demo_rehearsal_review",
        "n_run": len(rows),
        "failures": [
            {
                "id": r["id"],
                "locus": r["failure_locus"],
                "enough_evidence": r["enough_evidence"],
                "gold_in_hybrid20": r["gold_in_hybrid20"],
                "gold_in_sol5": r["gold_in_sol5"],
                "gold_cited": r["gold_cited"],
                "answer_preview": (r["answer"] or "")[:240],
            }
            for r in fails
        ],
        "estimated_usd_this_run": payload["estimated_usd_this_run"],
        "estimated_usd_total_including_prior": payload["estimated_usd_total_including_prior"],
    }
    args.review.write_text(json.dumps(review, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    args.summary.write_text(
        json.dumps(
            {
                "n_questions_run": len(rows),
                "n_flagged": len(fails),
                "estimated_usd_this_run": payload["estimated_usd_this_run"],
                "estimated_usd_total_including_prior": payload["estimated_usd_total_including_prior"],
                "startup_seconds": payload["startup_seconds"],
                "stopped": stopped,
                "results_file": str(args.out),
                "review_file": str(args.review),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print("Wrote", args.out)
    print("Wrote", args.summary, "flagged", len(fails))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
