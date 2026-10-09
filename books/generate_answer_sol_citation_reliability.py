"""
Citation-reliability Sol experiment with a revised instruction.

Uses saved Qwen lists and frozen questions. Does not change production search.
Case list and eval rules must exist before API calls.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

from evaluate_qwen3_reranker_0_6b_local import load_chunks
from generate_answer_sol_quality_test import BOOKS, compact_sent, load_question, ordered_candidates
from local_env import load_local_env, openai_api_key_configured
from sol_answer_common import (
    ANSWER_SCHEMA,
    MODEL,
    REASONING_EFFORT,
    REVISED_INSTRUCTIONS,
    SERVICE_TIER,
    estimate_usd,
    redact,
    sanitize_citations,
)

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "outputs"
CASES_PATH = OUTPUT_DIR / "sol_citation_reliability_cases_and_rules.json"
OUT_PATH = OUTPUT_DIR / "sol_citation_reliability_results.json"
SUMMARY_PATH = OUTPUT_DIR / "sol_citation_reliability_summary.json"
ORIGINAL_RESULTS = OUTPUT_DIR / "sol_answer_quality_multi_book_results.json"
N_PASSAGES = 5
BUDGET_USD = 2.00
STOP_USD = 1.75


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def select_passages(row: dict, chunks: dict[int, dict], passage_set: str) -> list[dict]:
    ordered = ordered_candidates(row)
    if passage_set == "qwen_top5":
        picked = ordered[:N_PASSAGES]
    elif passage_set == "qwen_tail5":
        picked = ordered[15:20] if len(ordered) >= 20 else ordered[-N_PASSAGES:]
    else:
        raise ValueError(passage_set)
    sent = []
    for c in picked:
        cid = int(c["chunk_index"])
        rec = chunks[cid]
        sent.append(
            {
                "passage_id": cid,
                "page": rec.get("page"),
                "qwen_rank": int(c.get("rerank_rank") or c.get("rank")),
                "qwen_score": c.get("rerank_score"),
                "text": rec["text"],
            }
        )
    return sent


def call_sol(client, question: str, sent: list[dict]):
    passage_block = "\n\n".join(f"[passage_id={p['passage_id']}]\n{p['text']}" for p in sent)
    user_msg = f"Question:\n{question}\n\nPassages (use only these; cite passage_id values):\n{passage_block}"
    t0 = time.perf_counter()
    resp = client.responses.create(
        model=MODEL,
        service_tier=SERVICE_TIER,
        store=False,
        reasoning={"effort": REASONING_EFFORT},
        instructions=REVISED_INSTRUCTIONS,
        input=user_msg,
        text={
            "format": {
                "type": "json_schema",
                "name": "bookrag_grounded_answer",
                "strict": True,
                "schema": ANSWER_SCHEMA,
            }
        },
    )
    elapsed = time.perf_counter() - t0
    parsed = json.loads((resp.output_text or "").strip())
    usage_obj = resp.usage
    if hasattr(usage_obj, "model_dump"):
        usage = usage_obj.model_dump()
    else:
        usage = {
            "input_tokens": getattr(usage_obj, "input_tokens", None),
            "output_tokens": getattr(usage_obj, "output_tokens", None),
        }
    return parsed, elapsed, usage, getattr(resp, "service_tier", None), getattr(resp, "id", None)


def original_snapshot(original: dict | None, case_id: str | None) -> dict | None:
    if not original or not case_id:
        return None
    row = next((q for q in original.get("questions") or [] if q.get("case_id") == case_id or q.get("question_id") == case_id), None)
    if row is None:
        return None
    return {
        "case_id": row.get("case_id"),
        "answer": (row.get("sol") or {}).get("answer"),
        "enough_evidence": (row.get("sol") or {}).get("enough_evidence"),
        "supporting_passage_ids": (row.get("sol") or {}).get("supporting_passage_ids"),
        "display_citations": row.get("display_citations"),
        "missing_evidence": (row.get("sol") or {}).get("missing_evidence"),
        "api_time_seconds": row.get("api_time_seconds"),
        "cost_usd": (row.get("cost") or {}).get("estimated_usd"),
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Sol citation reliability experiment.")
    p.add_argument("--cases", type=Path, default=CASES_PATH)
    p.add_argument("--out", type=Path, default=OUT_PATH)
    p.add_argument("--summary", type=Path, default=SUMMARY_PATH)
    p.add_argument("--budget-usd", type=float, default=BUDGET_USD)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if not args.cases.is_file():
        print(f"Missing frozen cases file {args.cases}; write rules before API calls.")
        return 2
    if args.out.exists() or args.summary.exists():
        print("Refusing to overwrite existing citation-reliability files.")
        return 2

    spec = json.loads(args.cases.read_text(encoding="utf-8"))
    if not spec.get("frozen_before_api_calls"):
        print("Cases file is not marked frozen_before_api_calls.")
        return 2
    cases = spec["cases"]
    if not 4 <= len(cases) <= 8:
        print("Expected about six preselected cases.")
        return 2

    loaded_from = load_local_env()
    if not openai_api_key_configured():
        print("OPENAI_API_KEY is not set in gitignored books/.env. Do not paste the key into chat.")
        return 2

    original = None
    if ORIGINAL_RESULTS.is_file():
        original = json.loads(ORIGINAL_RESULTS.read_text(encoding="utf-8"))

    from openai import OpenAI

    client = OpenAI()
    cache: dict[str, dict] = {}
    rows = []
    spent = 0.0

    for case in cases:
        if spent >= STOP_USD:
            print(f"Stopping before {case['id']}: spent ${spent:.4f}")
            break
        book = BOOKS[case["book"]]
        qid = case["question_id"]
        if case["book"] not in cache:
            qwen = json.loads(book["qwen"].read_text(encoding="utf-8"))
            eval_sha = sha256_file(book["eval"])
            expected = book.get("eval_sha256")
            if book.get("freeze"):
                expected = json.loads(book["freeze"].read_text(encoding="utf-8"))["sha256"]
            if expected and eval_sha != expected:
                raise RuntimeError(f"Frozen eval hash changed for {case['book']}")
            cache[case["book"]] = {
                "qwen": qwen,
                "chunks": load_chunks(book["chunks"]),
                "eval_sha": eval_sha,
            }
        pack = cache[case["book"]]
        row = load_question(pack["qwen"], qid)
        sent = select_passages(row, pack["chunks"], case["passage_set"])
        gold = [int(i) for i in row["gold_chunk_indexes"]]
        try:
            parsed, elapsed, usage, tier, resp_id = call_sol(client, row["question"], sent)
        except Exception as exc:
            print(redact(str(exc)))
            break
        cost = estimate_usd(usage)
        spent += float(cost["estimated_usd"])
        cited_raw = [int(i) for i in parsed.get("supporting_passage_ids") or []]
        citation_gate = sanitize_citations(cited_raw, sent)
        rec = {
            "case_id": case["id"],
            "pair": case["pair"],
            "question_id": qid,
            "book": case["book"],
            "book_id": pack["qwen"].get("book_id"),
            "question": row["question"],
            "passage_set": case["passage_set"],
            "expected_evidence": case["expected_evidence"],
            "desired_behavior": case["desired_behavior"],
            "retrieval_gold_chunk_indexes": gold,
            "gold_in_sent": bool(set(gold) & {p["passage_id"] for p in sent}),
            "instruction": "revised_scene_and_citation",
            "passages_sent": compact_sent(sent),
            "sol": {
                "answer": parsed.get("answer"),
                "enough_evidence": parsed.get("enough_evidence"),
                "missing_evidence": parsed.get("missing_evidence"),
                "supporting_passage_ids_raw": cited_raw,
                "supporting_passage_ids": citation_gate["accepted_passage_ids"],
            },
            "display_citations": citation_gate["display_citations"],
            "rejected_citations": citation_gate["rejected_citations"],
            "citation_gate": citation_gate["note"],
            "original_instruction_run": original_snapshot(original, case.get("compare_original_case_id")),
            "api_time_seconds": round(elapsed, 3),
            "usage": usage,
            "cost": cost,
            "service_tier_returned": tier,
            "response_id": resp_id,
            "eval_sha256": pack["eval_sha"],
        }
        rows.append(rec)
        print(
            f"{case['id']} enough={parsed.get('enough_evidence')} "
            f"cited={citation_gate['accepted_passage_ids']} rejected={citation_gate['rejected_citations']} "
            f"${cost['estimated_usd']:.4f} total=${spent:.4f} {elapsed:.1f}s"
        )
        if spent >= args.budget_usd:
            print("Hit budget cap; stopping.")
            break

    payload = {
        "experiment": "sol_citation_reliability",
        "production_pipeline_changed": False,
        "general_improvement_claimed": False,
        "model": MODEL,
        "instruction": "revised_scene_and_citation",
        "cases_file": str(args.cases),
        "cases_sha256": sha256_file(args.cases),
        "service_tier_requested": SERVICE_TIER,
        "reasoning_effort": REASONING_EFFORT,
        "budget_usd": args.budget_usd,
        "estimated_usd_total": round(spent, 6),
        "n_cases_planned": len(cases),
        "n_cases_run": len(rows),
        "env_file_loaded": bool(loaded_from),
        "gold_ids_sent_to_sol": False,
        "questions": rows,
    }
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    args.summary.write_text(
        json.dumps(
            {
                "n_cases_run": len(rows),
                "estimated_usd_total": payload["estimated_usd_total"],
                "cases_file": str(args.cases),
                "results_file": str(args.out),
                "production_pipeline_changed": False,
                "general_improvement_claimed": False,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {args.out}")
    print(f"Wrote {args.summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
