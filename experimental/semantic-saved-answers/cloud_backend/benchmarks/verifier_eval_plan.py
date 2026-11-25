#!/usr/bin/env python3
"""Budget for a future live verifier comparison. Refuses to call a provider."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

# Published gpt-6.1-sol Standard rates from DEPLOYMENT_READINESS_REPORT (26 Oct 2026).
# gpt-6-luna has no rate in this repository, so both models are budgeted at the
# Sol rates. That is a ceiling, not a quote for Luna.
SOL_INPUT_PER_MILLION = 2.0
SOL_OUTPUT_PER_MILLION = 10.0
ASSUMED_INPUT_TOKENS = 900
ASSUMED_OUTPUT_TOKENS = 80
PAIRS = 300
MODELS = ("gpt-6-luna", "gpt-6.1-sol")
RETRY_FACTOR = 1.2


def budget() -> dict:
    calls = PAIRS * len(MODELS)
    input_tokens = calls * ASSUMED_INPUT_TOKENS
    output_tokens = calls * ASSUMED_OUTPUT_TOKENS
    usd = (input_tokens * SOL_INPUT_PER_MILLION + output_tokens * SOL_OUTPUT_PER_MILLION) / 1_000_000
    ceiling = round(usd * RETRY_FACTOR, 2)
    return {
        "status": "NOT_RUN",
        "paid_api_calls": 0,
        "models": list(MODELS),
        "labeled_pairs": {"dev": 60, "heldout": 240, "total": PAIRS},
        "calls_if_approved": calls,
        "assumed_input_tokens_per_call": ASSUMED_INPUT_TOKENS,
        "assumed_output_tokens_per_call": ASSUMED_OUTPUT_TOKENS,
        "rate_basis": "gpt-6.1-sol Standard $2 input / $10 output per million tokens, applied to both models",
        "estimated_usd_before_retries": round(usd, 2),
        "estimated_usd_with_20_percent_retry_allowance": ceiling,
        "approval_cap_usd": 5.00,
        "measures": [
            "false_reuse_count",
            "exact_answer_reuse_precision",
            "paraphrase_recognition_recall",
            "latency_ms",
            "input_tokens",
            "output_tokens",
            "estimated_usd",
        ],
        "heldout_rule": "Score the 240 held-out pairs only after the dev split is inspected. Do not tune prompts on the held-out split.",
        "note": "Simulated verifier responses are not evidence that either live model meets the false-reuse bar.",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    if args.live:
        print("REFUSED: live GPT-6 Luna / GPT-6.1 Sol evaluation requires spending approval.")
        return 2
    report = budget()
    path = Path(__file__).with_name("verifier_eval_budget.json")
    path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"wrote": str(path), "approval_cap_usd": report["approval_cap_usd"], "paid_api_calls": 0}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
