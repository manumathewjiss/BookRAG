"""
Freeze wording-sensitivity retrieval cases BEFORE any search change.

No Sol calls. Does not overwrite earlier result files or frozen eval golds.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "outputs" / "sol_wording_sensitivity_cases.json"

BOOK_IDS = {
    "frankenstein": "frankenstein_1532610843_print",
    "pride": "pride_and_prejudice",
    "thinkpython": "thinkpython",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    if OUT.exists():
        print("Refusing to overwrite", OUT)
        return 2

    cases = [
        # --- Difficult / wording-sensitive ---
        {
            "id": "pp_016_frozen_wording",
            "source": "frozen_eval",
            "question_id": "pp_016",
            "book": "pride",
            "book_id": BOOK_IDS["pride"],
            "question": "When Mr Collins wants to speak privately to Elizabeth, what does Mrs Bennet insist that Lizzy do?",
            "gold_passage_ids": [132],
            "role": "difficult_nearby_line",
            "expects_answerable": True,
            "notes": "Original frozen wording. Neighboring 131 often retrieved instead of 132.",
        },
        {
            "id": "darcy_opening_words_no_quote",
            "source": "live_demo_wording",
            "question_id": None,
            "book": "pride",
            "book_id": BOOK_IDS["pride"],
            "question": "What were Darcy's exact opening words when he first proposed to Elizabeth?",
            "gold_passage_ids": [236],
            "role": "wording_sensitive_no_quote",
            "expects_answerable": True,
            "notes": "Live demo miss: opening words without the distinctive phrase.",
        },
        {
            "id": "darcy_opening_with_quote_hint",
            "source": "live_demo_wording",
            "question_id": None,
            "book": "pride",
            "book_id": BOOK_IDS["pride"],
            "question": 'What were Darcy\'s exact opening words when he first proposed to Elizabeth, beginning "In vain I have struggled"?',
            "gold_passage_ids": [236],
            "role": "wording_sensitive_with_quote",
            "expects_answerable": True,
            "notes": "Same ask with a distinctive phrase present in the question.",
        },
        {
            "id": "pp_021_frozen_wording",
            "source": "frozen_eval",
            "question_id": "pp_021",
            "book": "pride",
            "book_id": BOOK_IDS["pride"],
            "question": "When Mr Darcy unexpectedly walks into the Hunsford parsonage sitting-room, how does he begin his first proposal to Elizabeth?",
            "gold_passage_ids": [236],
            "role": "difficult_proposal_opening",
            "expects_answerable": True,
            "notes": "Frozen pp_021; gold often missing from hybrid top-20.",
        },
        {
            "id": "live_fr_why_second_creature",
            "source": "live_demo",
            "question_id": None,
            "book": "frankenstein",
            "book_id": BOOK_IDS["frankenstein"],
            "question": "Why does Victor stop making a second creature?",
            "gold_passage_ids": [397],
            "role": "why_later_explanation",
            "expects_answerable": True,
            "notes": "Later explanation in 397; reason may be found without the island scene.",
        },
        # --- Known successes ---
        {
            "id": "fr_011_creation",
            "source": "frozen_eval",
            "question_id": "fr_011",
            "book": "frankenstein",
            "book_id": BOOK_IDS["frankenstein"],
            "question": "On what kind of November night does Victor finish his toils, what time is it, and what does he see when the creature's dull yellow eye opens?",
            "gold_passage_ids": [77],
            "role": "known_success",
            "expects_answerable": True,
        },
        {
            "id": "fr_022_wedding_threat",
            "source": "frozen_eval",
            "question_id": "fr_022",
            "book": "frankenstein",
            "book_id": BOOK_IDS["frankenstein"],
            "question": "After Victor refuses to make a female companion, what exact threat does the creature utter as he goes, and in what does Victor then see him shoot across the water?",
            "gold_passage_ids": [298],
            "role": "known_success_exact_quote",
            "expects_answerable": True,
        },
        {
            "id": "pp_001_opening",
            "source": "frozen_eval",
            "question_id": "pp_001",
            "book": "pride",
            "book_id": BOOK_IDS["pride"],
            "question": "What truth is universally acknowledged in the opening of Pride and Prejudice about a single man in possession of a good fortune?",
            "gold_passage_ids": [1],
            "role": "known_success",
            "expects_answerable": True,
        },
        {
            "id": "pp_007_tolerable",
            "source": "frozen_eval",
            "question_id": "pp_007",
            "book": "pride",
            "book_id": BOOK_IDS["pride"],
            "question": "When Mr Bingley urges Darcy to dance at the assembly and points out Elizabeth sitting down, what does Darcy say about her looks and about giving consequence to young ladies?",
            "gold_passage_ids": [12],
            "role": "known_success_exact_quote",
            "expects_answerable": True,
        },
        {
            "id": "tp2_001_portable",
            "source": "frozen_eval",
            "question_id": "tp2_001",
            "book": "thinkpython",
            "book_id": BOOK_IDS["thinkpython"],
            "question": "What advantages of high-level languages does Think Python emphasize, and what does it mean for a language to be portable?",
            "gold_passage_ids": [66],
            "role": "known_success",
            "expects_answerable": True,
        },
        {
            "id": "tp2_014_recursion",
            "source": "frozen_eval",
            "question_id": "tp2_014",
            "book": "thinkpython",
            "book_id": BOOK_IDS["thinkpython"],
            "question": "What is infinite recursion, and what error does Python report when the maximum recursion depth is reached?",
            "gold_passage_ids": [144],
            "role": "known_success",
            "expects_answerable": True,
        },
        # --- Unanswerable / missing ---
        {
            "id": "tp_missing_tensorflow",
            "source": "live_demo",
            "question_id": None,
            "book": "thinkpython",
            "book_id": BOOK_IDS["thinkpython"],
            "question": "According to this book, how do you install TensorFlow and PyTorch?",
            "gold_passage_ids": [],
            "role": "unanswerable",
            "expects_answerable": False,
            "notes": "Book does not cover those libraries.",
        },
        {
            "id": "fr_missing_smartphone",
            "source": "synthetic_unanswerable",
            "question_id": None,
            "book": "frankenstein",
            "book_id": BOOK_IDS["frankenstein"],
            "question": "According to this book, what smartphone model does Walton use to message Margaret?",
            "gold_passage_ids": [],
            "role": "unanswerable",
            "expects_answerable": False,
        },
        {
            "id": "pp_missing_email",
            "source": "synthetic_unanswerable",
            "question_id": None,
            "book": "pride",
            "book_id": BOOK_IDS["pride"],
            "question": "According to this book, what is Elizabeth Bennet's email address?",
            "gold_passage_ids": [],
            "role": "unanswerable",
            "expects_answerable": False,
        },
    ]

    eval_paths = {
        "frankenstein": ROOT / "outputs" / "frankenstein_retrieval_eval_frozen_30.json",
        "pride": ROOT / "outputs" / "pride_and_prejudice_retrieval_eval_frozen_30.json",
        "thinkpython": ROOT / "outputs" / "thinkpython_retrieval_eval_frozen_30.json",
    }

    payload = {
        "artifact": "sol_wording_sensitivity_cases",
        "frozen_before_search_change": True,
        "frozen_eval_questions_unchanged": True,
        "gold_ids_sent_to_sol": False,
        "n_questions": len(cases),
        "methods_to_compare": [
            "baseline_hybrid20_qwen5",
            "dual_query_merge_hybrid20_qwen5",
        ],
        "dual_query_rule": {
            "name": "original_plus_at_most_one_alternative_phrasing",
            "hardcoded_book_names": False,
            "hardcoded_question_ids": False,
            "injects_gold_words": False,
            "description": (
                "Search the original question. If a general rule produces one alternative "
                "phrasing (quoted span already in the question, or a light speech/wording "
                "rewrite), search that too, merge/dedupe via RRF, and still send 20 to Qwen. "
                "Qwen scores against the original question."
            ),
        },
        "scoring": {
            "separate_correct_passage_found_from_answer_correct": True,
            "separate_citation_supports_claim": True,
            "quote_words_must_appear_in_cited_passage_text": True,
            "do_not_tune_to_one_book_or_qid": True,
        },
        "eval_sha256": {k: sha(v) for k, v in eval_paths.items()},
        "cases": cases,
    }
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("wrote", OUT, "n", len(cases), "sha", sha(OUT))
    for c in cases:
        print(c["id"], "gold", c["gold_passage_ids"], "role", c["role"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
