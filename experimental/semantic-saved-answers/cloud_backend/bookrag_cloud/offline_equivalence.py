"""Deterministic offline equivalence oracle for benchmarks and unit tests.

This is NOT used in production. Production uses HostedModels.verify_question_equivalence.
The oracle encodes the same strict rubric so hard-negative cases can fail closed offline
without paid API calls.
"""
from __future__ import annotations

import re
import unicodedata

from .equivalence import validate_equivalence_payload

_WHITESPACE = re.compile(r"\s+")
_NON_WORD = re.compile(r"[^\w\s']+", re.UNICODE)


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").strip().lower()
    text = text.replace("'", "'").replace("`", "'")
    text = _NON_WORD.sub(" ", text)
    return _WHITESPACE.sub(" ", text).strip()


def _tokens(text: str) -> set[str]:
    return set(_norm(text).split())


# Ordinals / polarity / WH markers that flip meaning when they differ.
_CRITICAL = {
    "first", "second", "third", "fourth", "fifth", "last", "only",
    "not", "never", "no", "without",
    "who", "what", "when", "where", "why", "how", "which",
    "before", "after", "during",
}


def _critical_differs(a: set[str], b: set[str]) -> bool:
    return bool((a & _CRITICAL) ^ (b & _CRITICAL))


# Hand-authored paraphrase families for offline recall tests.
_PARAPHRASE_FAMILIES: list[set[str]] = [
    {
        _norm("Who was the first person to walk on the Moon?"),
        _norm("Who first stepped onto the lunar surface?"),
        _norm("Who was the first human to walk on the Moon?"),
        _norm("Name the first person to walk on the Moon."),
    },
    {
        _norm("Who is Neil Armstrong?"),
        _norm("Who was Neil Armstrong?"),
        _norm("Who was Neil Armstrong really?"),
    },
]


def _same_family(left: str, right: str) -> bool:
    a, b = _norm(left), _norm(right)
    if a == b:
        return True
    for family in _PARAPHRASE_FAMILIES:
        if a in family and b in family:
            return True
    return False


def _reuse(reason: str) -> dict:
    return {
        "decision": "REUSE_EXACT_ANSWER",
        "equivalent": True,
        "answer_satisfies_unchanged": True,
        "citations_support": True,
        "omits_requested_information": False,
        "confidence": "high",
        "reason": reason,
    }


def _reject(reason: str, *, confidence: str = "high") -> dict:
    return {
        "decision": "RUN_FULL_RAG",
        "equivalent": False,
        "answer_satisfies_unchanged": False,
        "citations_support": False,
        "omits_requested_information": True,
        "confidence": confidence,
        "reason": reason,
    }


def offline_verify_equivalence(
    new_question: str,
    saved_question: str,
    saved_answer: str,
    *,
    enough_evidence: bool,
) -> dict:
    """Return a validated decision dict using the offline rubric."""
    new_t, saved_t = _tokens(new_question), _tokens(saved_question)
    if _same_family(new_question, saved_question):
        payload = _reuse("offline_paraphrase_family")
    elif _norm(new_question) == _norm(saved_question):
        payload = _reuse("offline_exact")
    elif _critical_differs(new_t, saved_t):
        payload = _reject("offline_critical_token_diff")
    elif not enough_evidence and new_t != saved_t:
        # Saved refusals: only reuse when questions are the same family/exact.
        payload = _reject("offline_refusal_not_equivalent")
    else:
        # Conservative default for unmatched paraphrases offline.
        payload = _reject("offline_uncertain", confidence="low")
    validated = validate_equivalence_payload(payload)
    assert validated is not None
    return validated
