#!/usr/bin/env python3
"""Offline benchmark for rule-based vs semantic saved-answer matching.

Default mode uses the deterministic offline oracle (no paid API calls).
Results are labeled SIMULATED unless --live is passed (requires approval + keys).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bookrag_cloud.equivalence import should_reuse_exact_answer
from bookrag_cloud.offline_equivalence import offline_verify_equivalence
from bookrag_cloud.question_match import is_same_question


CASES_PATH = Path(__file__).with_name("semantic_saved_answers_cases.json")

# Rough public list prices used only for offline cost *estimates* (USD / 1M tokens).
# Not a billing guarantee. Update when comparing live models.
COST = {
    "voyage_embed_per_mtok": 0.12,
    "gpt_6_luna_in_per_mtok": 0.10,
    "gpt_6_luna_out_per_mtok": 0.40,
    "gpt_5_nano_in_per_mtok": 0.05,
    "gpt_5_nano_out_per_mtok": 0.20,
    # Assumed tokens per semantic verify call (SIMULATED).
    "verify_in_tokens": 350,
    "verify_out_tokens": 60,
    "embed_tokens": 25,
}


def load_cases() -> list[dict]:
    data = json.loads(CASES_PATH.read_text())
    return data["cases"]


def isolation_blocks(case: dict) -> bool:
    return not (
        case.get("same_user", True)
        and case.get("same_document", True)
        and case.get("same_sha", True)
        and case.get("same_pipeline", True)
    )


def rule_decision(case: dict) -> str:
    if isolation_blocks(case):
        return "RUN_FULL_RAG"
    if is_same_question(case["new_question"], case["saved_question"]):
        return "REUSE_EXACT_ANSWER"
    return "RUN_FULL_RAG"


def semantic_offline_decision(case: dict) -> str:
    if isolation_blocks(case):
        return "RUN_FULL_RAG"
    # Stage 0 first (mirrors production cascade).
    if is_same_question(case["new_question"], case["saved_question"]):
        return "REUSE_EXACT_ANSWER"
    payload = offline_verify_equivalence(
        case["new_question"],
        case["saved_question"],
        case["saved_answer"],
        enough_evidence=bool(case.get("enough_evidence", True)),
    )
    return "REUSE_EXACT_ANSWER" if should_reuse_exact_answer(payload) else "RUN_FULL_RAG"


def evaluate(name: str, decide, cases: list[dict]) -> dict:
    started = time.perf_counter()
    rows = []
    false_reuse = 0
    true_reuse = 0
    expected_reuse = 0
    missed_reuse = 0
    for case in cases:
        expected = case["expected"]
        if expected == "REUSE_EXACT_ANSWER":
            expected_reuse += 1
        got = decide(case)
        ok = got == expected
        if got == "REUSE_EXACT_ANSWER" and expected != "REUSE_EXACT_ANSWER":
            false_reuse += 1
        if got == "REUSE_EXACT_ANSWER" and expected == "REUSE_EXACT_ANSWER":
            true_reuse += 1
        if got != "REUSE_EXACT_ANSWER" and expected == "REUSE_EXACT_ANSWER":
            missed_reuse += 1
        rows.append({
            "id": case["id"],
            "category": case["category"],
            "expected": expected,
            "got": got,
            "ok": ok,
            "critical_hard_negative": bool(case.get("critical_hard_negative")),
        })
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    n = len(cases)
    precision = (true_reuse / (true_reuse + false_reuse)) if (true_reuse + false_reuse) else 1.0
    recall = (true_reuse / expected_reuse) if expected_reuse else 1.0
    hard_negatives = [r for r in rows if r["critical_hard_negative"]]
    hard_neg_fail = [r for r in hard_negatives if r["got"] == "REUSE_EXACT_ANSWER"]
    return {
        "matcher": name,
        "mode": "SIMULATED_OFFLINE",
        "sample_size": n,
        "exact_answer_reuse_precision": round(precision, 4),
        "paraphrase_recognition_recall": round(recall, 4),
        "false_reuse_count": false_reuse,
        "false_reuse_rate": round(false_reuse / n, 4) if n else 0.0,
        "true_reuse_count": true_reuse,
        "missed_reuse_count": missed_reuse,
        "hard_negative_count": len(hard_negatives),
        "hard_negative_false_reuse_count": len(hard_neg_fail),
        "latency_total_ms": elapsed_ms,
        "latency_avg_ms": round(elapsed_ms / n, 3) if n else 0.0,
        "cases": rows,
        "hard_negative_failures": [r["id"] for r in hard_neg_fail],
    }


def estimate_costs(semantic_result: dict) -> dict:
    """Cost model for semantic Stage-1 probes (SIMULATED; no live API)."""
    n = semantic_result["sample_size"]
    # Exact/rule hits need $0 Stage-1; approximate Stage-1 attempts as non-rule reuse candidates.
    # Conservative: charge embed+verify for every case that is not an isolation block and not
    # caught by rules — use case count * mix.
    embed = COST["embed_tokens"]
    vin, vout = COST["verify_in_tokens"], COST["verify_out_tokens"]
    per_probe_usd = (
        embed * COST["voyage_embed_per_mtok"]
        + vin * COST["gpt_6_luna_in_per_mtok"]
        + vout * COST["gpt_6_luna_out_per_mtok"]
    ) / 1_000_000
    # Assume ~70% of questions miss Stage 0 and need a semantic probe in production traffic.
    probe_rate = 0.70
    return {
        "mode": "ESTIMATED_NOT_MEASURED_LIVE",
        "assumptions": {
            "probe_rate": probe_rate,
            "embed_tokens": embed,
            "verify_in_tokens": vin,
            "verify_out_tokens": vout,
            "model": "gpt-6-luna",
            "prices": COST,
        },
        "usd_per_probe": round(per_probe_usd, 8),
        "usd_per_100_questions": round(100 * probe_rate * per_probe_usd, 6),
        "usd_per_1000_questions": round(1000 * probe_rate * per_probe_usd, 6),
        "benchmark_sample_size": n,
        "alt_gpt_5_nano_usd_per_1000": round(
            1000 * probe_rate * (
                embed * COST["voyage_embed_per_mtok"]
                + vin * COST["gpt_5_nano_in_per_mtok"]
                + vout * COST["gpt_5_nano_out_per_mtok"]
            ) / 1_000_000,
            6,
        ),
        "note": "Cheapest model is not automatically selected; accuracy on hard negatives comes first.",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="Disallowed without approval; exits.")
    args = parser.parse_args()
    if args.live:
        print("REFUSED: live Voyage/OpenAI benchmark requires explicit spending approval.")
        return 2
    cases = load_cases()
    rule = evaluate("rules_v1", rule_decision, cases)
    semantic = evaluate("semantic_v1_offline_oracle", semantic_offline_decision, cases)
    costs = estimate_costs(semantic)
    report = {
        "result_kind": "SIMULATED_OFFLINE",
        "paid_api_calls": 0,
        "rule_based": rule,
        "semantic": semantic,
        "cost_estimates": costs,
        "release_gate": {
            "hard_negative_false_reuse_must_be_zero": semantic["hard_negative_false_reuse_count"] == 0,
            "passing_benchmark_does_not_guarantee_perfect_accuracy": True,
        },
    }
    out = Path(__file__).with_name("semantic_saved_answers_benchmark_results.json")
    out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({
        "wrote": str(out),
        "rule_precision": rule["exact_answer_reuse_precision"],
        "rule_recall": rule["paraphrase_recognition_recall"],
        "rule_false_reuse": rule["false_reuse_count"],
        "semantic_precision": semantic["exact_answer_reuse_precision"],
        "semantic_recall": semantic["paraphrase_recognition_recall"],
        "semantic_false_reuse": semantic["false_reuse_count"],
        "hard_negative_false_reuse": semantic["hard_negative_false_reuse_count"],
        "usd_per_1000_est": costs["usd_per_1000_questions"],
    }, indent=2))
    if semantic["hard_negative_false_reuse_count"] != 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
