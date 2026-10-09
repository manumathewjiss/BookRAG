"""
Freeze passages for the answer-support vs nearby-scene comparison.

No Sol calls. Does not overwrite earlier case files or frozen eval questions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from generate_answer_sol_quality_test import BOOKS

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "outputs"
HELD = OUTPUT_DIR / "sol_heldout_answer_quality_cases.json"
OUT = OUTPUT_DIR / "sol_answer_support_vs_nearby_cases.json"

QWEN_FILES = {
    "frankenstein": OUTPUT_DIR / "frankenstein_qwen3_reranker_hybrid_pool20_results.json",
    "pride": OUTPUT_DIR / "pride_and_prejudice_qwen3_reranker_0_6b_pool20_results.json",
    "thinkpython": OUTPUT_DIR / "thinkpython_qwen3_reranker_0_6b_local_retrieval_results_30.json",
}

EVAL_FILES = {
    "frankenstein": OUTPUT_DIR / "frankenstein_retrieval_eval_frozen_30.json",
    "pride": OUTPUT_DIR / "pride_and_prejudice_retrieval_eval_frozen_30.json",
    "thinkpython": OUTPUT_DIR / "thinkpython_retrieval_eval_frozen_30.json",
}

BOOK_IDS = {
    "frankenstein": "frankenstein_1532610843_print",
    "pride": "pride_and_prejudice",
    "thinkpython": "thinkpython",
}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_eval(book: str) -> dict:
    rows = json.loads(EVAL_FILES[book].read_text(encoding="utf-8"))
    return {r["id"]: r for r in rows}


def load_qwen(book: str) -> dict:
    data = json.loads(QWEN_FILES[book].read_text(encoding="utf-8"))
    questions = data.get("questions") or data.get("results") or data
    if isinstance(questions, dict):
        questions = questions.get("questions") or []
    return {q["id"]: q for q in questions}


def top5_from_qwen(book: str, qid: str, qwen: dict, eval_row: dict) -> dict:
    rec = qwen[qid]
    cands = sorted(rec["candidates"], key=lambda c: c.get("rerank_rank") or 10**9)[:5]
    gold = eval_row["gold_chunk_indexes"]
    sent_ids = [int(c["chunk_index"]) for c in cands]
    gold_in = any(g in sent_ids for g in gold)
    passages = []
    for i, c in enumerate(cands, start=1):
        passages.append(
            {
                "passage_id": int(c["chunk_index"]),
                "page": c.get("page"),
                "qwen_rank": i,
                "n_chars": None,
                "text_preview": (c.get("text_preview") or "")[:180],
            }
        )
    return {
        "id": f"{qid}_qwen_top5",
        "question_id": qid,
        "book": book,
        "book_id": BOOK_IDS[book],
        "question": eval_row["question"],
        "passage_set": "qwen_top5",
        "gold_in_sent": gold_in,
        "retrieval_gold_chunk_indexes": gold,
        "passages": passages,
        "qwen_results": QWEN_FILES[book].name,
        "eval_sha256": sha256_file(EVAL_FILES[book]),
    }


def from_heldout(held: dict, case_id: str) -> dict:
    by = {c["id"]: c for c in held["cases"]}
    return dict(by[case_id])


def live_case(engine, case_id: str, book: str, question: str, role: str) -> dict:
    demo_id = BOOK_IDS[book]
    ranked = engine.retrieve_top5(demo_id, question)
    passages = []
    for i, p in enumerate(ranked["top"], start=1):
        passages.append(
            {
                "passage_id": p["passage_id"],
                "page": p["page"],
                "qwen_rank": i,
                "n_chars": len(p["text"]),
                "text_preview": p["text"][:180].replace("\n", " "),
            }
        )
    return {
        "id": case_id,
        "question_id": case_id,
        "book": book,
        "book_id": demo_id,
        "question": question,
        "passage_set": "live_hybrid20_qwen_top5",
        "gold_in_sent": None,
        "retrieval_gold_chunk_indexes": [],
        "passages": passages,
        "hybrid_pool20_ids": [h["passage_id"] for h in ranked["hybrid"]],
        "role": role,
        "frozen_live_retrieve": True,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, default=OUT)
    p.add_argument("--include-live", action="store_true")
    args = p.parse_args()
    if args.out.exists():
        print("Refusing to overwrite", args.out)
        return 2

    held = json.loads(HELD.read_text(encoding="utf-8"))
    cases = []

    # Live Frankenstein pair from the local demo session (Qwen frozen below).
    live_specs = [
        (
            "live_fr_why_second_creature",
            "Why does Victor stop making a second creature?",
            "why_later_explanation",
        ),
        (
            "live_fr_november_creation",
            "On what kind of November night does Victor finish his toils, what time is it, and what does he see when the creature's dull yellow eye opens?",
            "exact_scene",
        ),
    ]

    # Saved Qwen top-5 / held-out nearby cases. Frozen eval questions unchanged.
    saved = [
        ("why", "pride", "pp_011", "qwen"),
        ("why", "thinkpython", "tp2_005", "qwen"),
        ("why", "thinkpython", "tp2_006", "qwen"),
        ("why", "frankenstein", "fr_029", "qwen"),
        ("exact_quote_or_scene", "pride", "pp_007", "qwen"),
        ("exact_quote_or_scene", "frankenstein", "fr_018", "held", "fr_018_qwen_top5"),
        ("exact_quote_or_scene", "frankenstein", "fr_022", "qwen"),
        ("nearby_or_missing", "pride", "pp_016", "held", "pp_016_qwen_top5"),
        ("nearby_or_missing", "pride", "pp_021", "held", "pp_021_qwen_top5"),
        ("nearby_or_missing", "frankenstein", "fr_005", "held", "fr_005_qwen_tail5"),
        ("nearby_or_missing", "thinkpython", "tp2_012", "held", "tp2_012_qwen_tail5"),
    ]

    qwen_cache: dict = {}
    eval_cache: dict = {}
    for item in saved:
        role, book, qid, src = item[0], item[1], item[2], item[3]
        if src == "held":
            case = from_heldout(held, item[4])
        else:
            if book not in qwen_cache:
                qwen_cache[book] = load_qwen(book)
                eval_cache[book] = load_eval(book)
            case = top5_from_qwen(book, qid, qwen_cache[book], eval_cache[book][qid])
        case["role"] = role
        cases.append(case)

    if args.include_live:
        sys.path.insert(0, str(ROOT / "demo"))
        from pipeline import DemoEngine

        engine = DemoEngine()
        live_cases = []
        for cid, question, role in live_specs:
            live_cases.append(live_case(engine, cid, "frankenstein", question, role))
        cases = live_cases + cases

    spec = {
        "artifact": "sol_answer_support_vs_nearby_cases",
        "frozen_before_api_calls": True,
        "gold_ids_sent_to_sol": False,
        "same_passages_both_instructions": True,
        "frozen_eval_questions_unchanged": True,
        "n_questions": len(cases),
        "n_api_calls_planned": len(cases) * 2,
        "instructions_to_run": [
            "revised_plus_nearby_event_check",
            "answer_support_direct_or_later_explanation",
        ],
        "model": "gpt-6.1-sol",
        "service_tier": "default",
        "reasoning_effort": "low",
        "already_tracked_sol_usd": 1.075128,
        "stop_usd_including_already_tracked": 18.0,
        "hard_limit_usd": 20.0,
        "proposed_rule": {
            "name": "direct_answer_vs_nearby_vs_absent",
            "hardcoded_question_ids": False,
            "hardcoded_character_names": False,
            "direct_answer": "Passage states the asked fact, reason, line, or detail, including a later explanation of a reason.",
            "nearby_only": "Same people/place/conversation but missing the requested detail, including a neighboring line.",
            "absent": "No useful evidence.",
            "later_explanation_must_be_named_in_the_answer": True,
        },
        "scoring": {
            "why_later_explanation_should_be_supported": True,
            "pp_016_must_not_become_overconfident": True,
            "nearby_scene_cases_must_not_become_overconfident": True,
            "do_not_declare_winner_from_enough_evidence_flag_alone": True,
        },
        "cases": cases,
    }
    args.out.write_text(json.dumps(spec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("wrote", args.out, "n", len(cases), "sha", sha256_file(args.out))
    for c in cases:
        ids = [p["passage_id"] for p in c["passages"]]
        print(c["id"], c["role"], "ids", ids, "gold_in", c.get("gold_in_sent"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
