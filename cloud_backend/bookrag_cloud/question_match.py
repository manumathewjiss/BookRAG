"""Strict saved-question keys for Saved Answers v1.

Only an exact canonical repeat may reuse a stored answer. A missed reuse is
acceptable. A changed character that could change the fact must not match.

Rows saved under an earlier canonicalizer used pipeline version
``voyage-4-large+rerank-3+gpt-6.1-sol-v1``. This release looks up only
``ANSWER_PIPELINE_VERSION``. Those older keys are left in place and are not
read, because their normalized text could collide with a different question.
"""
from __future__ import annotations

import re
import unicodedata

# Cache namespace. The model stack is unchanged; the suffix isolates keys that
# were produced by the retired lowercase / punctuation-stripping canonicalizer.
ANSWER_PIPELINE_VERSION = "voyage-4-large+rerank-3+gpt-6.1-sol-v1+strict-q-v1"
LEGACY_PIPELINE_VERSION = "voyage-4-large+rerank-3+gpt-6.1-sol-v1"

_REPEATED_WHITESPACE = re.compile(r"\s+")
_ONE_FINAL_QUESTION_MARK = re.compile(r"\s*\?\s*$")

# Apostrophe-like marks only. Possessive "'s" stays attached to the word.
_APOSTROPHE = {
    "\u2018": "'",  # left single quotation mark
    "\u2019": "'",  # right single quotation mark
    "\u201b": "'",  # single high-reversed-9 quotation mark
    "\u2032": "'",  # prime
    "\u02bc": "'",  # modifier letter apostrophe
    "`": "'",
    "´": "'",
}


def canonicalize_question(question: str) -> str:
    """Return the exact-match key.

    Trim ends, collapse repeated whitespace, ignore one trailing question mark,
    and fold apostrophe glyphs to "'". Capitalization, internal punctuation,
    numbers, word order, tense, pronouns, conjunctions, and negation stay.
    """
    text = unicodedata.normalize("NFC", question or "")
    text = "".join(_APOSTROPHE.get(char, char) for char in text)
    text = text.strip()
    text = _REPEATED_WHITESPACE.sub(" ", text)
    text = _ONE_FINAL_QUESTION_MARK.sub("", text)
    return text.strip()


def question_signature(question: str) -> dict:
    """Stored beside the answer. Matching does not interpret this structure."""
    return {"canonical": canonicalize_question(question), "policy": "strict-v1"}


def is_same_question(new_question: str, saved_question: str) -> bool:
    """True only when the strict canonical keys are identical and non-empty."""
    left = canonicalize_question(new_question)
    right = canonicalize_question(saved_question)
    return bool(left) and left == right
