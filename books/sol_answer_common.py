"""
Shared helpers for separate Sol answer experiments (not production search).

Never log API keys. Citation ID/page checks do not prove a passage supports the answer.
"""

from __future__ import annotations

import re
from typing import Any

MODEL = "gpt-6.1-sol"
SERVICE_TIER = "default"
REASONING_EFFORT = "low"

INPUT_PER_M = 2.00
CACHED_INPUT_PER_M = 0.10
CACHE_WRITE_PER_M = 2.50
OUTPUT_PER_M = 10.00
LONG_CONTEXT_INPUT_TOKENS = 272_000

ORIGINAL_INSTRUCTIONS = """You answer one question using only the numbered passages provided.
Do not use outside knowledge. Do not invent page numbers.
Write a short answer (a few sentences at most).
If the passages do not contain enough evidence, say so clearly and do not guess.
Return JSON with:
- answer: the short answer, or a statement that evidence is missing
- supporting_passage_ids: passage_id integers from the provided list that actually support the answer
- enough_evidence: true only if those passages contain the needed facts
- missing_evidence: empty string if enough_evidence is true, otherwise what is missing
"""

REVISED_INSTRUCTIONS = """You answer one question using only the numbered passages provided.
Do not use outside knowledge. Do not invent page numbers.
Write a short answer (a few sentences at most).

Answer the specific scene or detail the question asks about. Do not treat a nearby
page, a later repeat of a similar fact, or a passage that only shares names as if it
were that scene.

Cite only passage_id values from the provided list. Cite a passage only when it
directly supports a claim in your answer. Do not add extra citations for colour,
background, or nearby chapters.

If you have only a related passage or a later repeat rather than the requested scene,
say that clearly, describe only what those passages actually contain, set
enough_evidence to false, and explain what is missing. Do not guess the requested scene.

enough_evidence is true only when the provided passages contain the exact scene or
detail asked about.

Return JSON with:
- answer: the short answer, a qualified statement about related material, or a statement that evidence is missing
- supporting_passage_ids: passage_id integers from the provided list that directly support the claims in answer
- enough_evidence: true only if the passages contain the requested scene or detail
- missing_evidence: empty string if enough_evidence is true, otherwise what is missing
"""

# One general check: exact line/event/scene vs a neighboring moment.
# Do not special-case books, characters, or question IDs.
NEARBY_EVENT_CHECK = """
One evidence check for a specific line, event, or scene:

First name the distinctive line, event, or scene the question asks you to recover
(the wording, the occasion, or the fact that makes that moment different from
the sentence before or after it).

Then classify the supplied passages as exactly one of:
- exact: at least one passage contains that line, event, or scene itself
- nearby_only: the passages only contain a neighboring moment — the previous or
  next sentence, the same people in a similar action, or a weaker/later version
  of the same kind of event — but not the asked moment
- absent: the passages contain neither that moment nor a neighbor of it

enough_evidence may be true only when the classification is exact.
If the classification is nearby_only or absent, do not present a certain answer.
Qualify in answer: state what the passages actually contain, state that they do
not contain the asked line/event/scene, and set enough_evidence to false.
Sharing names, a place, or a similar action is not enough.
Do not broaden or weaken asked_event to fit a neighboring passage. Keep the
question's distinctive constraints (the specific utterance, occasion, or fact).
A neighboring utterance in the same conversation — including an earlier weaker
request or a later related command — is nearby_only, not exact.
Do not infer the next line from a nearby line.
This check uses only the supplied passages, never later knowledge of the book.
Also return asked_event (the distinctive moment you named) and event_match
(exact, nearby_only, or absent).
"""

EVIDENCE_CHECK_INSTRUCTIONS = REVISED_INSTRUCTIONS.rstrip() + "\n" + NEARBY_EVENT_CHECK

EVENT_MATCH_VALUES = ("exact", "nearby_only", "absent")

# Book-independent: a later explanation can directly answer a "why" question;
# a neighboring line that lacks the asked detail cannot.
ANSWER_SUPPORT_CHECK = """
One evidence check: does any supplied passage directly answer the question?

Classify the supplied passages as exactly one of:
- direct_answer: at least one passage states the fact, reason, line, or detail
  the question asks for. That passage may be a later explanation, a memoir, or
  another chapter than the original event. That still counts as a direct answer,
  but the answer text must preserve that context (for example, that the reason
  is given in a later account) rather than implying the original scene was retrieved.
- nearby_only: the passages are about the same people, place, or conversation
  but they do not contain the requested fact, reason, or wording. A neighboring
  sentence in the same conversation is nearby_only if it lacks the asked line.
- absent: the passages do not answer the question and are not a nearby miss.

enough_evidence may be true only for direct_answer.
Cite only passages that actually support a claim in the answer.
Every claim in the answer must be supported by a cited displayed passage.
Do not treat sharing names or a similar action as a direct answer.
Do not infer a missing line from a neighboring line.
This check uses only the supplied passages.
Also return asked_event (the fact, reason, or line the question asks for)
and event_match (direct_answer, nearby_only, or absent).
"""

ANSWER_SUPPORT_INSTRUCTIONS = REVISED_INSTRUCTIONS.rstrip() + "\n" + ANSWER_SUPPORT_CHECK

ANSWER_SUPPORT_MATCH_VALUES = ("direct_answer", "nearby_only", "absent")

ANSWER_SCHEMA_WITH_ANSWER_SUPPORT = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "supporting_passage_ids": {"type": "array", "items": {"type": "integer"}},
        "enough_evidence": {"type": "boolean"},
        "missing_evidence": {"type": "string"},
        "asked_event": {"type": "string"},
        "event_match": {"type": "string", "enum": list(ANSWER_SUPPORT_MATCH_VALUES)},
    },
    "required": [
        "answer",
        "supporting_passage_ids",
        "enough_evidence",
        "missing_evidence",
        "asked_event",
        "event_match",
    ],
    "additionalProperties": False,
}

ANSWER_SCHEMA_WITH_EVENT_MATCH = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "supporting_passage_ids": {"type": "array", "items": {"type": "integer"}},
        "enough_evidence": {"type": "boolean"},
        "missing_evidence": {"type": "string"},
        "asked_event": {"type": "string"},
        "event_match": {"type": "string", "enum": list(EVENT_MATCH_VALUES)},
    },
    "required": [
        "answer",
        "supporting_passage_ids",
        "enough_evidence",
        "missing_evidence",
        "asked_event",
        "event_match",
    ],
    "additionalProperties": False,
}

ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "supporting_passage_ids": {"type": "array", "items": {"type": "integer"}},
        "enough_evidence": {"type": "boolean"},
        "missing_evidence": {"type": "string"},
    },
    "required": ["answer", "supporting_passage_ids", "enough_evidence", "missing_evidence"],
    "additionalProperties": False,
}

SECRET_RE = re.compile(r"(sk-[A-Za-z0-9_\-]+)|(Bearer\s+\S+)|(OPENAI_API_KEY\s*=\s*\S+)", re.I)


def redact(text: str) -> str:
    return SECRET_RE.sub("[REDACTED]", text)


def estimate_usd(usage: dict[str, Any]) -> dict[str, Any]:
    input_tokens = int(usage.get("input_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or 0)
    details = usage.get("input_tokens_details") or {}
    cached = int(details.get("cached_tokens") or 0)
    cache_writes = int(
        details.get("cache_write_tokens")
        or details.get("cache_creation_tokens")
        or usage.get("cache_creation_input_tokens")
        or 0
    )
    uncached = max(0, input_tokens - cached)
    long_ctx = input_tokens > LONG_CONTEXT_INPUT_TOKENS
    in_m = (4.00 if long_ctx else INPUT_PER_M) / 1_000_000
    cached_m = (0.20 if long_ctx else CACHED_INPUT_PER_M) / 1_000_000
    write_m = (5.00 if long_ctx else CACHE_WRITE_PER_M) / 1_000_000
    out_m = (15.00 if long_ctx else OUTPUT_PER_M) / 1_000_000
    usd = uncached * in_m + cached * cached_m + cache_writes * write_m + output_tokens * out_m
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cached_input_tokens": cached,
        "cache_write_tokens": cache_writes,
        "long_context_rates": long_ctx,
        "processing": "standard",
        "estimated_usd": round(usd, 6),
        "pricing_note": (
            "Standard gpt-6.1-sol list rates: $2 / $0.10 cached / $2.50 cache write / "
            "$10 output per 1M tokens; 2x input and 1.5x output if input > 272K."
        ),
    }


def sanitize_citations(raw_ids: list[int], sent: list[dict]) -> dict[str, Any]:
    """Keep cited IDs that were sent; pages only from Stage 1 metadata on those IDs.

    Rejected citations are dropped from display. Passing this check does not mean
    the passage supports the answer.
    """
    sent_by_id = {int(p["passage_id"]): p for p in sent}
    accepted: list[dict] = []
    rejected: list[dict] = []
    seen: set[int] = set()
    for raw in raw_ids:
        cid = int(raw)
        if cid in seen:
            rejected.append({"passage_id": cid, "reason": "duplicate_citation"})
            continue
        seen.add(cid)
        if cid not in sent_by_id:
            rejected.append({"passage_id": cid, "reason": "not_in_sent_passages"})
            continue
        page = sent_by_id[cid].get("page")
        if page is None:
            rejected.append({"passage_id": cid, "reason": "missing_stage1_page"})
            continue
        accepted.append(
            {
                "passage_id": cid,
                "page": page,
                "page_source": "stage1_chunk_metadata",
            }
        )
    return {
        "display_citations": accepted,
        "rejected_citations": rejected,
        "accepted_passage_ids": [c["passage_id"] for c in accepted],
        "note": "ID-in-sent and Stage 1 page checks only; not a support judgment.",
    }


def apply_event_match_gate(parsed: dict[str, Any]) -> dict[str, Any]:
    """Force enough_evidence false unless the match is a direct answer.

    `exact` is the older nearby-scene label. `direct_answer` is the current
    label and also covers a later explanation of a reason. General: does not
    inspect question IDs, character names, or gold passages.
    """
    out = dict(parsed)
    match = str(out.get("event_match") or "").strip().lower()
    if match in {"direct_answer", "exact"}:
        out["enough_evidence"] = bool(out.get("enough_evidence"))
        out["event_match_gate"] = "unchanged"
        return out
    out["enough_evidence"] = False
    allowed = set(EVENT_MATCH_VALUES) | set(ANSWER_SUPPORT_MATCH_VALUES)
    if match in allowed:
        out["event_match_gate"] = "forced_false_because_not_direct_answer"
    else:
        out["event_match_gate"] = "forced_false_unknown_event_match"
        out["event_match"] = match or "unknown"
    return out


def reader_evidence_label(event_match: str, enough: bool, n_passages: int) -> str:
    """Reader-facing evidence wording for the local demo. Not a support proof."""
    match = (event_match or "").strip().lower()
    if enough and match in {"direct_answer", "exact"}:
        return "Answer supported by this passage" if n_passages <= 1 else "Answer supported by these passages"
    if n_passages:
        return "Related passage only"
    return "The supplied passages do not answer this question"
