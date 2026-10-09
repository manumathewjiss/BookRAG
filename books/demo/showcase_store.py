"""Append-only store of demo Q&A cases for professor showcasing."""

from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PATH = ROOT / "outputs" / "demo_showcase_cases.json"
_LOCK = threading.Lock()

_SECRETISH_RE = re.compile(r"(?i)(sk-[A-Za-z0-9_\-]{8,}|api[_-]?key\s*[:=]\s*\S+)")


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _slug(text: str, *, max_len: int = 48) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", (text or "").strip().lower()).strip("_")
    return (cleaned or "case")[:max_len]


def _safe_text(value: Any, *, limit: int | None = None) -> str:
    text = _SECRETISH_RE.sub("[redacted]", str(value or ""))
    if limit is not None and len(text) > limit:
        return text[: limit - 1] + "…"
    return text


def empty_store() -> dict[str, Any]:
    return {
        "artifact": "demo_showcase_cases",
        "purpose": "Saved BookRAG demo Q&A for live showcasing (query, answer, PDF evidence).",
        "created_at": _utc_now(),
        "updated_at": _utc_now(),
        "n_cases": 0,
        "cases": [],
    }


def load_store(path: Path = DEFAULT_PATH) -> dict[str, Any]:
    if not path.is_file():
        return empty_store()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty_store()
    if not isinstance(data, dict):
        return empty_store()
    cases = data.get("cases")
    if not isinstance(cases, list):
        cases = []
    data["cases"] = cases
    data["n_cases"] = len(cases)
    data.setdefault("artifact", "demo_showcase_cases")
    return data


def case_from_result(
    result: dict[str, Any],
    *,
    index_seconds: float | None = None,
    browser_wait_seconds: float | None = None,
    note: str = "",
) -> dict[str, Any]:
    """Build a compact showcase record from a live /ask result."""
    book_id = _safe_text(result.get("book_id") or "book", limit=80)
    question = _safe_text(result.get("question") or "", limit=2000)
    saved_at = _utc_now()
    stamp = saved_at.replace(":", "").replace("-", "")
    case_id = f"{_slug(book_id, max_len=24)}_{_slug(question, max_len=32)}_{stamp[-6:]}"

    evidence = []
    for p in result.get("supporting_passages") or []:
        if not isinstance(p, dict):
            continue
        evidence.append(
            {
                "passage_id": p.get("passage_id"),
                "pdf_page": p.get("page"),
                "page_label": p.get("page_label") or "PDF page",
                "excerpt": _safe_text(p.get("excerpt") or "", limit=1200),
                "excerpt_reliable": bool(p.get("excerpt_reliable")),
                "excerpt_note": _safe_text(p.get("excerpt_note") or "", limit=240),
                "full_passage": _safe_text(p.get("text") or "", limit=8000),
                "qwen_score": p.get("qwen_score"),
            }
        )

    citations = []
    for c in result.get("citations") or []:
        if not isinstance(c, dict):
            continue
        citations.append(
            {
                "passage_id": c.get("passage_id"),
                "pdf_page": c.get("page"),
                "page_label": c.get("page_label") or "PDF page",
            }
        )

    timings = result.get("timings_seconds") if isinstance(result.get("timings_seconds"), dict) else {}
    answer_seconds = timings.get("total_wait")
    total_seconds = None
    if index_seconds is not None or answer_seconds is not None:
        total_seconds = round(
            (float(index_seconds) if index_seconds is not None else 0.0)
            + (float(answer_seconds) if answer_seconds is not None else 0.0),
            3,
        )

    return {
        "id": case_id,
        "saved_at": saved_at,
        "book_id": book_id,
        "book_label": _safe_text(result.get("book_label") or book_id, limit=160),
        "question": question,
        "answer": _safe_text(result.get("answer") or "", limit=4000),
        "enough_evidence": bool(result.get("enough_evidence")),
        "evidence_label": _safe_text(result.get("evidence_label") or "", limit=240),
        "event_match": _safe_text(result.get("event_match") or "", limit=80),
        "asked_event": _safe_text(result.get("asked_event") or "", limit=240),
        "citations": citations,
        "evidence": evidence,
        "qwen_top5_ids": list(result.get("qwen_top5_ids") or []),
        "timings_seconds": {
            "index_embed": round(float(index_seconds), 3) if index_seconds is not None else None,
            "retrieve_hybrid": timings.get("retrieve_hybrid"),
            "qwen_rerank": timings.get("qwen_rerank"),
            "sol_api": timings.get("sol_api"),
            "answer_total_wait": timings.get("total_wait"),
            "browser_wait": round(float(browser_wait_seconds), 3) if browser_wait_seconds is not None else None,
            "combined_index_plus_answer": total_seconds,
            "combined_minutes": round(total_seconds / 60.0, 2) if total_seconds is not None else None,
        },
        "retrieval_method": result.get("retrieval_method") or "baseline_hybrid20_qwen5",
        "note": _safe_text(note, limit=400),
    }


def append_case(
    result: dict[str, Any],
    *,
    path: Path = DEFAULT_PATH,
    index_seconds: float | None = None,
    browser_wait_seconds: float | None = None,
    note: str = "",
) -> dict[str, Any]:
    """Append one showcase case to disk. Returns the saved case + store summary."""
    if not isinstance(result, dict) or not (result.get("question") or "").strip():
        raise ValueError("Need a completed answer result to save.")
    case = case_from_result(
        result,
        index_seconds=index_seconds,
        browser_wait_seconds=browser_wait_seconds,
        note=note,
    )
    with _LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        store = load_store(path)
        store.setdefault("cases", []).append(case)
        store["n_cases"] = len(store["cases"])
        store["updated_at"] = _utc_now()
        store.setdefault("created_at", store["updated_at"])
        store.setdefault("artifact", "demo_showcase_cases")
        store.setdefault(
            "purpose",
            "Saved BookRAG demo Q&A for live showcasing (query, answer, PDF evidence).",
        )
        path.write_text(json.dumps(store, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "case": case,
        "path": str(path),
        "n_cases": store["n_cases"],
        "updated_at": store["updated_at"],
    }
