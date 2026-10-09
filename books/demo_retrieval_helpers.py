"""
General, book-independent helpers for dual-query retrieval and quote checks.

Used by the local demo experiment only. Does not change frozen eval golds.
"""

from __future__ import annotations

import re
from typing import Any


# Prefer double / curly-double quotes. Do not treat apostrophes as quote delimiters.
DOUBLE_QUOTE_RE = re.compile(r'[“"]([^”"\n]{8,160})[”"]')
# Single quotes only when clearly paired (space or start before; punctuation/end after).
SINGLE_QUOTE_RE = re.compile(r"(?:^|[\s(])'([^'\n]{8,160})'(?=[\s).,;:!?]|$)")

SPEECH_HINT_RE = re.compile(
    r"\b(exact\s+)?(opening\s+)?words?\b|\bhow does\b.+\bbegin\b|\bwhat does\b.+\bsay\b|"
    r"\bwhat (were|was|did)\b.+\b(say|said|speak|spoke|utter)\b|"
    r"\binsist(?:s|ed)?\b|\bthreat\b|\bquote\b",
    re.I,
)


def one_alternative_phrasing(question: str) -> str | None:
    """At most one deterministic rewrite. No book names or gold lines injected.

    Priority:
    1. If the question already contains a short double-quoted span, search that span alone
       (strong lexical signal when the asker already knows a distinctive phrase).
    2. Else, for wording/speech questions, lightly rephrase without adding content.
    3. Else None (baseline search only).
    """
    q = (question or "").strip()
    if len(q) < 8:
        return None

    quoted = DOUBLE_QUOTE_RE.findall(q)
    if quoted:
        span = re.sub(r"\s+", " ", quoted[0]).strip(" .;:,")
        if len(span) >= 8:
            return span

    if not SPEECH_HINT_RE.search(q):
        return None

    alt = q
    # "What were X's (exact/opening) words when Y" → "What did X say when Y"
    alt2 = re.sub(
        r"\bWhat were\s+(.+?)(?:'s)?\s+(?:exact\s+)?(?:opening\s+)?words\b",
        r"What did \1 say",
        alt,
        flags=re.I,
    )
    if alt2 != alt:
        alt = alt2
    else:
        alt = re.sub(r"\bexact\s+", "", alt, flags=re.I)
        alt = re.sub(r"\bopening\s+words\b", "words", alt, flags=re.I)
        alt = re.sub(r"\bWhat were\b", "What did", alt, flags=re.I)
        alt = re.sub(r"\bwhat were\b", "what did", alt, flags=re.I)
        alt = re.sub(r"\bwhen (he|she|they) first\b", r"when \1", alt, flags=re.I)
        alt = re.sub(
            r"\bhow does ([^.?]+?) begin (his|her|their|the)\b",
            r"what does \1 say at the start of \2",
            alt,
            flags=re.I,
        )
    alt = re.sub(r"\s+", " ", alt).strip()
    # Clean "What did Darcy's say" → "What did Darcy say"
    alt = re.sub(r"\b(did|does)\s+(.+?)'s\s+say\b", r"\1 \2 say", alt, flags=re.I)
    if alt.lower() == q.lower() or len(alt) < 8:
        return None
    return alt


def normalize_quote_text(text: str) -> str:
    """Normalize PDF extraction quirks for quote containment checks."""
    t = text or ""
    t = t.replace("\u00ad", "")  # soft hyphen
    t = t.replace("\u0018", "")
    # line-break hyphenation: "IN -\nSIST" / "ardent-\nly"
    t = re.sub(r"-\s*\n\s*", "", t)
    t = re.sub(r"(?<=\w)-\s+(?=\w)", "", t)
    t = t.replace("\n", " ")
    t = re.sub(r"\s+", " ", t)
    # curly quotes → straight
    for a, b in (("“", '"'), ("”", '"'), ("‘", "'"), ("’", "'")):
        t = t.replace(a, b)
    return t.lower().strip()


def extract_quoted_spans(answer: str) -> list[str]:
    spans = []
    for m in DOUBLE_QUOTE_RE.finditer(answer or ""):
        s = m.group(1).strip()
        if len(s) >= 8:
            spans.append(s)
    for m in SINGLE_QUOTE_RE.finditer(answer or ""):
        s = m.group(1).strip()
        if len(s) >= 8:
            spans.append(s)
    return spans


def quoted_spans_supported_by_citations(answer: str, cited_texts: list[str]) -> dict[str, Any]:
    """Every quoted span in the answer must appear in some cited passage text.

    Passing an ID-in-sent check is not enough; the words must be in the text.
    """
    spans = extract_quoted_spans(answer)
    if not spans:
        return {
            "asks_or_uses_quotes": False,
            "spans": [],
            "all_supported": True,
            "unsupported": [],
            "note": "No quoted spans of length >= 8 in the answer.",
        }
    blob = " ".join(normalize_quote_text(t) for t in cited_texts)
    unsupported = []
    details = []
    for span in spans:
        norm = normalize_quote_text(span).strip(" .,;:!?\"'")
        ok = bool(norm) and (norm in blob or normalize_quote_text(span) in blob)
        details.append({"span": span, "supported": ok})
        if not ok:
            unsupported.append(span)
    return {
        "asks_or_uses_quotes": True,
        "spans": details,
        "all_supported": not unsupported,
        "unsupported": unsupported,
        "note": "Quote support requires the normalized words to appear in a cited passage.",
    }


# Display-only stopwords for picking a supporting sentence window.
_DISPLAY_STOP = frozenset(
    """
    a an the and or but if then else when while of to for from with without into onto
    in on at by as is are was were be been being it its this that these those he she
    they them their his her him we us our you your what which who whom whose how why
    do does did done have has had having will would can could should may might must
    not no nor so than too very just also only about into over after before between
    said says say according book passage question answer
    """.split()
)

_BOILERPLATE_RES = (
    re.compile(r"(?is)Copyright\s*©?\s*\d{4}\s+The\s+Bhaktivedanta\s+Book\s+Trust[^.]*\.\s*"),
    re.compile(r"(?is)All\s+Rights\s+Reserved\.?\s*"),
    re.compile(r"(?im)\bFree eBooks at Planet eBook\.com\b\s*"),
    re.compile(r"(?im)^Pride and Prejudice\s+"),
    re.compile(r"(?im)^Chapter\s+\d+\s*$"),
    # Generic press/scan crumbs (display only; not book-title rules).
    re.compile(r"(?im)^\s*-more-\s*$"),
    re.compile(r"(?im)^\s*-\s*\d{1,4}\s*-\s*$"),
    re.compile(r"(?is)\bRELEASE\s+NO:\s*[A-Z0-9-]+\b"),
)

# A single OCR/layout junk line (not a real sentence).
_OCR_JUNK_LINE_RE = re.compile(
    r"^(?:[A-Za-z|\\/.'’`]{1,2}|[-_.…]{1,6}|\d{1,3}|-\s*\d{1,4}\s*-)$"
)

_NUMBER_WORDS = {
    "0": "zero",
    "1": "one",
    "2": "two",
    "3": "three",
    "4": "four",
    "5": "five",
    "6": "six",
    "7": "seven",
    "8": "eight",
    "9": "nine",
    "10": "ten",
    "11": "eleven",
    "12": "twelve",
    "20": "twenty",
    "50": "fifty",
    "100": "hundred",
}


def _strip_leading_ocr_junk_lines(text: str) -> str:
    """Drop leading one-token OCR/layout lines only; keep the first real sentence line."""
    lines = (text or "").splitlines()
    i = 0
    while i < len(lines):
        s = lines[i].strip()
        if not s:
            i += 1
            continue
        if _OCR_JUNK_LINE_RE.fullmatch(s):
            i += 1
            continue
        break
    return "\n".join(lines[i:])


def strip_display_boilerplate(text: str) -> str:
    """Remove obvious header/copyright/control junk for display only.

    Does not change stored retrieval text. Avoids rewriting numbers, names, or quotes.
    """
    t = text or ""
    t = t.replace("\u00ad", "")
    # Drop non-printing controls but keep newlines/tabs until hyphenation is fixed.
    t = re.sub(r"[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]", "", t)
    t = _strip_leading_ocr_junk_lines(t)
    for pat in _BOILERPLATE_RES:
        t = pat.sub(" ", t)
    # Digit-only page crumbs sometimes glued to headers (e.g. "181Free eBooks…")
    t = re.sub(r"(?m)^\s*\d{1,4}(?=[A-Za-z“\"'])", "", t)
    t = re.sub(r"-\s*\n\s*", "", t)
    t = re.sub(r"\s*\n\s*", " ", t)
    # PDF hyphenation left as "Col - lins" / "Col -lins" after newline flattening
    t = re.sub(r"(?<=\w)\s+-\s*(?=\w)", "", t)
    # Common scan join where a hyphen was lost inside a compound (display only).
    t = re.sub(r"\b([A-Za-z]{3,})-?per(second|minute|hour|cent)\b", r"\1-per-\2", t, flags=re.I)
    # Stray isolated letters stuck before a capitalized sentence start.
    t = re.sub(r"(?:(?<=\s)|^)[A-Za-z]\s+(?=[A-Z][a-z]{2,})", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    # Trim leftover punctuation crumbs at the start.
    t = re.sub(r"^[\s|\\/.'’`~,_:;]+", "", t)
    return t


def _content_tokens(text: str) -> list[str]:
    toks = re.findall(r"[A-Za-z0-9']{3,}", (text or "").lower())
    return [t for t in toks if t not in _DISPLAY_STOP]


def _answer_cues(answer: str) -> dict[str, float]:
    """Token weights plus numeric/percent cues from the answer."""
    weights: dict[str, float] = {}
    for t in _content_tokens(answer):
        weights[t] = weights.get(t, 0.0) + 1.5
    for num in re.findall(r"\d+", answer or ""):
        weights[num] = weights.get(num, 0.0) + 2.0
        word = _NUMBER_WORDS.get(num)
        if word:
            weights[word] = weights.get(word, 0.0) + 2.0
        # percent often written as words in PDFs
        if "%" in (answer or "") or "percent" in (answer or "").lower():
            weights["percent"] = weights.get("percent", 0.0) + 1.0
    return weights


def _sentence_cue_score(sent: str, weights: dict[str, float], answer_toks: list[str]) -> tuple[float, int]:
    stoks = set(_content_tokens(sent))
    slow = sent.lower()
    for cue in weights:
        if cue.isdigit():
            if re.search(rf"(?<!\d){re.escape(cue)}(?!\d)", slow):
                stoks.add(cue)
        elif re.search(rf"\b{re.escape(cue)}\b", slow):
            stoks.add(cue)
    if not stoks or not weights:
        return 0.0, 0
    score = sum(weights[t] for t in stoks if t in weights)
    hit = sum(1 for t in answer_toks if t in stoks)
    # Prefer sentences that carry multiple numeric claims (e.g. 5% and 10%).
    num_hits = sum(1 for t, w in weights.items() if w >= 2.0 and t in stoks)
    if num_hits >= 2:
        score += 3.0
    if hit >= 3:
        score += 1.0
    return score, hit



def _window_around(text: str, start: int, end: int, *, max_chars: int) -> str:
    if end <= start:
        start, end = 0, min(len(text), max_chars)
    center = (start + end) // 2
    half = max_chars // 2
    left = max(0, center - half)
    right = min(len(text), left + max_chars)
    left = max(0, right - max_chars)
    # Prefer word boundaries
    if left > 0:
        sp = text.find(" ", left)
        if sp != -1 and sp < right - 20:
            left = sp + 1
    if right < len(text):
        sp = text.rfind(" ", left + 20, right)
        if sp != -1:
            right = sp
    out = text[left:right].strip()
    if left > 0:
        out = "…" + out
    if right < len(text):
        out = out + "…"
    return out


def clean_display_excerpt(text: str, *, max_chars: int = 420) -> str:
    """Legacy start-truncated excerpt. Prefer select_supporting_excerpt for citations."""
    t = strip_display_boilerplate(text)
    if len(t) <= max_chars:
        return t
    cut = t[: max_chars - 1].rsplit(" ", 1)[0]
    return cut + "…"


def select_supporting_excerpt(
    passage_text: str,
    answer: str,
    *,
    question: str = "",
    max_chars: int = 420,
    claim_enough_evidence: bool = True,
) -> dict[str, Any]:
    """Pick a short window around the sentence that supports the answer.

    Display-only. Does not alter stored passage text. If no reliable supporting
    sentence is found, excerpt_reliable is False so the UI must not treat the
    short snippet as proof.
    """
    cleaned = strip_display_boilerplate(passage_text)
    if not cleaned:
        return {
            "excerpt": "",
            "excerpt_reliable": False,
            "excerpt_anchor": "none",
            "excerpt_note": "No readable passage text after cleanup.",
        }

    if len(cleaned) <= max_chars:
        # Whole cleaned passage fits; still require an answer-overlap cue when claiming support.
        ans_toks = set(_content_tokens(answer))
        overlap = sum(1 for t in ans_toks if t in cleaned.lower()) if ans_toks else 0
        reliable = (not claim_enough_evidence) or overlap >= min(2, len(ans_toks)) or bool(
            extract_quoted_spans(answer)
            and any(normalize_quote_text(s) in normalize_quote_text(cleaned) for s in extract_quoted_spans(answer))
        )
        return {
            "excerpt": cleaned,
            "excerpt_reliable": bool(reliable),
            "excerpt_anchor": "full_short_passage" if reliable else "none",
            "excerpt_note": (
                "Full cleaned passage shown."
                if reliable
                else "Could not locate a supporting sentence; inspect the full passage."
            ),
        }

    # Prefer exact quoted spans from the answer that appear in this passage.
    for span in extract_quoted_spans(answer):
        norm_pass = normalize_quote_text(cleaned)
        norm_span = normalize_quote_text(span).strip(" .,;:!?\"'")
        if len(norm_span) < 8 or norm_span not in norm_pass:
            continue
        # Map back approximately via raw lowercase search
        raw_lower = cleaned.lower()
        idx = raw_lower.find(span.lower().strip(" .,;:!?\""))
        if idx < 0:
            # Fall back: search first ~12 content tokens of the quote
            toks = _content_tokens(span)
            needle = " ".join(toks[:8])
            idx = raw_lower.find(needle) if needle else -1
        if idx < 0:
            continue
        end = idx + max(len(span), 8)
        return {
            "excerpt": _window_around(cleaned, idx, end, max_chars=max_chars),
            "excerpt_reliable": True,
            "excerpt_anchor": "quoted_span",
            "excerpt_note": "Short window around quoted wording from the answer.",
        }

    answer_toks = _content_tokens(answer)
    weights = _answer_cues(answer)
    # Lightly include distinctive question tokens so paraphrased answers still land.
    for t in _content_tokens(question)[:12]:
        if t not in weights:
            weights[t] = 0.4

    sentences: list[tuple[int, int, str]] = []
    for m in re.finditer(r".+?(?:[.!?…]+[\"”’']?|\Z)", cleaned, flags=re.S):
        s = m.group(0).strip()
        if len(s) < 12:
            continue
        sentences.append((m.start(), m.end(), s))
    if not sentences:
        sentences = [(0, len(cleaned), cleaned)]

    best_i = -1
    best_score = 0.0
    best_hits = 0
    best_adjusted = -1.0
    for i, (_a, _b, sent) in enumerate(sentences):
        score, hit = _sentence_cue_score(sent, weights, answer_toks)
        # Long bullet dumps (e.g. KEY POINTS) can accumulate cues; prefer denser windows.
        adjusted = score / (1.0 + max(0, len(sent) - 320) / 240.0)
        if adjusted > best_adjusted or (adjusted == best_adjusted and hit > best_hits):
            best_score = score
            best_adjusted = adjusted
            best_hits = hit
            best_i = i

    # Reliability: need a clear overlap with the answer, not just the question.
    min_score = 2.5 if claim_enough_evidence else 1.5
    answer_hits = best_hits if best_i >= 0 else 0

    reliable = best_i >= 0 and best_score >= min_score and (
        answer_hits >= 2 or (answer_hits >= 1 and best_score >= 4.0) or best_score >= 6.0
    )

    if not reliable:
        return {
            "excerpt": "",
            "excerpt_reliable": False,
            "excerpt_anchor": "none",
            "excerpt_note": "Could not identify a reliable supporting sentence; inspect the full passage.",
        }

    # Expand one neighboring sentence if room remains.
    a, b, _ = sentences[best_i]
    if best_i > 0 and (b - sentences[best_i - 1][0]) <= max_chars:
        a = sentences[best_i - 1][0]
    if best_i + 1 < len(sentences) and (sentences[best_i + 1][1] - a) <= max_chars:
        b = sentences[best_i + 1][1]
    return {
        "excerpt": _window_around(cleaned, a, b, max_chars=max_chars),
        "excerpt_reliable": True,
        "excerpt_anchor": "sentence_overlap",
        "excerpt_note": "Short window around the sentence that overlaps the answer.",
    }
