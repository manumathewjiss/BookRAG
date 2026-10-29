"""Exact frozen-benchmark BM25 + dense top 30, RRF k=60, top 20."""
import math
import re
from collections import Counter

TOKEN_RE = re.compile(r"\w+", re.UNICODE)
K1 = 1.2
B = 0.75


def tokens(value: str) -> list[str]:
    return TOKEN_RE.findall(value.casefold())


def bm25_top(passages: list[dict], question: str, limit: int = 30) -> list[dict]:
    if not passages:
        return []
    counts = [Counter(tokens(p["text"])) for p in passages]
    lengths = [sum(c.values()) for c in counts]
    avg = sum(lengths) / len(lengths)
    df = Counter(term for c in counts for term in c)
    terms = set(tokens(question))
    scored = []
    for p, tf, length in zip(passages, counts, lengths):
        score = 0.0
        for term in terms:
            freq = tf.get(term, 0)
            if freq:
                idf = math.log(1 + (len(passages) - df[term] + .5) / (df[term] + .5))
                score += idf * freq * (K1 + 1) / (freq + K1 * (1 - B + B * length / avg))
        if score > 0:
            scored.append((score, p))
    scored.sort(key=lambda x: (-x[0], x[1]["chunk_index"]))
    return [p for _, p in scored[:limit]]


def fuse(dense: list[dict], lexical: list[dict], limit: int = 20) -> list[dict]:
    scores: dict[object, float] = {}
    by_id = {}
    for ranking in (dense, lexical):
        for position, p in enumerate(ranking, start=1):
            key = p["id"]
            by_id[key] = p
            scores[key] = scores.get(key, 0.0) + 1 / (60 + position)
    return [by_id[key] for key in sorted(scores, key=lambda key: (-scores[key], by_id[key]["chunk_index"]))[:limit]]
