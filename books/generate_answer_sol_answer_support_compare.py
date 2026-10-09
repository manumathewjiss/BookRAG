"""
Compare current nearby-scene Sol check vs direct-answer / later-explanation check.

Frozen passages only. Does not change production search or overwrite earlier files.
Gold passage IDs are not sent to Sol.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

from evaluate_qwen3_reranker_0_6b_local import load_chunks
from generate_answer_sol_quality_test import BOOKS
from local_env import load_local_env, openai_api_key_configured
from sol_answer_common import (
    ANSWER_SCHEMA_WITH_ANSWER_SUPPORT,
    ANSWER_SCHEMA_WITH_EVENT_MATCH,
    ANSWER_SUPPORT_INSTRUCTIONS,
    EVIDENCE_CHECK_INSTRUCTIONS,
    MODEL,
    REASONING_EFFORT,
    SERVICE_TIER,
    apply_event_match_gate,
    estimate_usd,
    redact,
    sanitize_citations,
)

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "outputs"
CASES_PATH = OUTPUT_DIR / "sol_answer_support_vs_nearby_cases.json"
OUT_PATH = OUTPUT_DIR / "sol_answer_support_vs_nearby_results.json"
SUMMARY_PATH = OUTPUT_DIR / "sol_answer_support_vs_nearby_summary.json"
STOP_USD = 18.0

INSTRUCTIONS = {
    "revised_plus_nearby_event_check": {
        "text": EVIDENCE_CHECK_INSTRUCTIONS,
        "schema": ANSWER_SCHEMA_WITH_EVENT_MATCH,
        "schema_name": "bookrag_grounded_answer_event_match",
    },
    "answer_support_direct_or_later_explanation": {
        "text": ANSWER_SUPPORT_INSTRUCTIONS,
        "schema": ANSWER_SCHEMA_WITH_ANSWER_SUPPORT,
        "schema_name": "bookrag_grounded_answer_support",
    },
}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def call_sol(client, spec: dict, question: str, sent: list[dict]):
    passage_block = "\n\n".join(f"[passage_id={p['passage_id']}]\n{p['text']}" for p in sent)
    user_msg = f"Question:\n{question}\n\nPassages (use only these; cite passage_id values):\n{passage_block}"
    t0 = time.perf_counter()
    resp = client.responses.create(
        model=MODEL,
        service_tier=SERVICE_TIER,
        store=False,
        reasoning={"effort": REASONING_EFFORT},
        instructions=spec["text"],
        input=user_msg,
        text={
            "format": {
                "type": "json_schema",
                "name": spec["schema_name"],
                "strict": True,
                "schema": spec["schema"],
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


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--cases", type=Path, default=CASES_PATH)
    p.add_argument("--out", type=Path, default=OUT_PATH)
    p.add_argument("--summary", type=Path, default=SUMMARY_PATH)
    p.add_argument("--stop-usd", type=float, default=STOP_USD)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if args.out.exists() or args.summary.exists():
        print("Refusing to overwrite answer-support result files.")
        return 2
    spec = json.loads(args.cases.read_text(encoding="utf-8"))
    if not spec.get("frozen_before_api_calls"):
        print("Cases file not frozen.")
        return 2
    loaded = load_local_env()
    if not openai_api_key_configured():
        print("OPENAI_API_KEY is not set in gitignored books/.env.")
        return 2

    from openai import OpenAI

    client = OpenAI()
    chunk_cache: dict[str, dict] = {}
    spent = float(spec.get("already_tracked_sol_usd") or 0)
    rows = []
    stopped = None

    for case in spec["cases"]:
        book = case["book"]
        if book not in chunk_cache:
            chunk_cache[book] = load_chunks(BOOKS[book]["chunks"])
        chunks = chunk_cache[book]
        sent = []
        for p in case["passages"]:
            cid = int(p["passage_id"])
            rec = chunks[cid]
            sent.append(
                {
                    "passage_id": cid,
                    "page": rec.get("page"),
                    "qwen_rank": p.get("qwen_rank"),
                    "text": rec["text"],
                }
            )
        pair = {
            "case_id": case["id"],
            "question_id": case["question_id"],
            "book": book,
            "role": case.get("role"),
            "question": case["question"],
            "gold_in_sent": case.get("gold_in_sent"),
            "retrieval_gold_chunk_indexes": case.get("retrieval_gold_chunk_indexes"),
            "passages_sent": [
                {"passage_id": p["passage_id"], "page": p["page"], "qwen_rank": p.get("qwen_rank")}
                for p in sent
            ],
            "runs": {},
        }
        for inst_name, inst in INSTRUCTIONS.items():
            if spent >= args.stop_usd:
                stopped = f"stop_usd {args.stop_usd} reached before {case['id']} {inst_name}"
                break
            try:
                parsed, elapsed, usage, tier, resp_id = call_sol(client, inst, case["question"], sent)
            except Exception as exc:
                print(redact(str(exc)))
                stopped = "api_error"
                break
            parsed = apply_event_match_gate(parsed)
            cost = estimate_usd(usage)
            spent += float(cost["estimated_usd"])
            cited_raw = [int(i) for i in parsed.get("supporting_passage_ids") or []]
            gate = sanitize_citations(cited_raw, sent)
            pair["runs"][inst_name] = {
                "answer": parsed.get("answer"),
                "enough_evidence": parsed.get("enough_evidence"),
                "missing_evidence": parsed.get("missing_evidence"),
                "asked_event": parsed.get("asked_event"),
                "event_match": parsed.get("event_match"),
                "event_match_gate": parsed.get("event_match_gate"),
                "supporting_passage_ids_raw": cited_raw,
                "supporting_passage_ids": gate["accepted_passage_ids"],
                "display_citations": gate["display_citations"],
                "rejected_citations": gate["rejected_citations"],
                "citation_gate": gate["note"],
                "api_time_seconds": round(elapsed, 3),
                "usage": usage,
                "cost": cost,
                "service_tier_returned": tier,
                "response_id": resp_id,
            }
            print(
                f"{case['id']} {inst_name} enough={parsed.get('enough_evidence')} "
                f"match={parsed.get('event_match')} cited={gate['accepted_passage_ids']} "
                f"${cost['estimated_usd']:.4f} total=${spent:.4f} {elapsed:.1f}s"
            )
        rows.append(pair)
        if stopped:
            break

    payload = {
        "experiment": "sol_answer_support_vs_nearby",
        "production_pipeline_changed": False,
        "cases_file": str(args.cases),
        "cases_sha256": sha256_file(args.cases),
        "already_tracked_sol_usd": spec.get("already_tracked_sol_usd"),
        "estimated_usd_total_including_prior": round(spent, 6),
        "estimated_usd_this_run": round(spent - float(spec.get("already_tracked_sol_usd") or 0), 6),
        "n_questions_planned": spec["n_questions"],
        "n_questions_run": len(rows),
        "stopped": stopped,
        "env_file_loaded": bool(loaded),
        "gold_ids_sent_to_sol": False,
        "questions": rows,
    }
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    args.summary.write_text(
        json.dumps(
            {
                "n_questions_run": len(rows),
                "estimated_usd_this_run": payload["estimated_usd_this_run"],
                "estimated_usd_total_including_prior": payload["estimated_usd_total_including_prior"],
                "stopped": stopped,
                "results_file": str(args.out),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {args.out}")
    print(f"Wrote {args.summary} total_including_prior=${spent:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
