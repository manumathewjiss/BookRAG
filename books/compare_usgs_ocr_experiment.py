#!/usr/bin/env python3
"""Compare baseline USGS index vs experimental low-text OCR index.

Retrieval checks are offline. Sol calls are optional and limited.
Does not overwrite prior evaluation artifacts.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DEMO = ROOT / "demo"
if str(DEMO) not in sys.path:
    sys.path.insert(0, str(DEMO))

from local_env import load_local_env  # noqa: E402


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def any_group_hit(text: str, groups: list[list[str]]) -> bool:
    low = (text or "").lower()
    if not groups:
        return False
    for group in groups:
        if not any(re.search(re.escape(g.lower()), low) for g in group):
            return False
    return True


def page_in_hits(hits: list[dict], pages: list[int]) -> bool:
    want = {int(p) for p in pages}
    return any(int(h.get("page") or -1) in want for h in hits)


def run_retrieval(engine, book_id: str, question: str) -> dict[str, Any]:
    t0 = time.perf_counter()
    ranked = engine.retrieve_top5(book_id, question)
    wait = round(time.perf_counter() - t0, 3)
    hybrid = ranked.get("hybrid") or []
    top = ranked.get("top") or []
    return {
        "retrieve_wait_s": wait,
        "timings_seconds": {
            "retrieve_hybrid": ranked.get("retrieve_s"),
            "qwen_rerank": ranked.get("qwen_s"),
        },
        "hybrid_pool20": [{"passage_id": h["passage_id"], "page": h.get("page")} for h in hybrid],
        "qwen_top5": [{"passage_id": p["passage_id"], "page": p.get("page")} for p in top],
    }


def run_ask(engine, book_id: str, question: str) -> dict[str, Any]:
    t0 = time.perf_counter()
    result = engine.ask(book_id, question)
    wait = round(time.perf_counter() - t0, 3)
    return {
        "ask_wait_s": wait,
        "answer": result.get("answer"),
        "enough_evidence": result.get("enough_evidence"),
        "evidence_label": result.get("evidence_label"),
        "citations": result.get("citations"),
        "supporting_passages": [
            {
                "passage_id": p.get("passage_id"),
                "page": p.get("page"),
                "excerpt": (p.get("excerpt") or "")[:400],
                "excerpt_reliable": p.get("excerpt_reliable"),
            }
            for p in (result.get("supporting_passages") or [])
        ],
        "timings_seconds": result.get("timings_seconds"),
        "cost": result.get("cost"),
    }


def score_case(case: dict, retrieval: dict, ask: dict | None) -> dict[str, Any]:
    pages = [int(p) for p in (case.get("expected_pdf_pages") or [])]
    hybrid_hit = page_in_hits(retrieval.get("hybrid_pool20") or [], pages) if pages else None
    top5_hit = page_in_hits(retrieval.get("qwen_top5") or [], pages) if pages else None
    expects = bool(case.get("expects_answerable"))
    out: dict[str, Any] = {
        "answer_bearing_page_in_hybrid20": hybrid_hit,
        "answer_bearing_page_in_qwen_top5": top5_hit,
    }
    if ask is None:
        out["sol_run"] = False
        return out
    out["sol_run"] = True
    answer = ask.get("answer") or ""
    enough = bool(ask.get("enough_evidence"))
    groups = case.get("expected_answer_contains_any") or []
    if expects:
        content_ok = any_group_hit(answer, groups) if groups else bool(answer.strip())
        out["final_answer_correct_for_asked_question"] = bool(enough and content_ok)
        out["refusal_or_qualification_appropriate"] = None
    else:
        # Appropriate if it refuses or clearly says it cannot establish current/visual facts.
        refused = (not enough) or bool(
            re.search(r"cannot|not (enough|stated|in|available)|do not|don't|no .*evidence", answer, re.I)
        )
        out["final_answer_correct_for_asked_question"] = None
        out["refusal_or_qualification_appropriate"] = refused
    cites = ask.get("citations") or []
    if pages and cites:
        out["each_cited_passage_supports_answer"] = all(int(c.get("page") or -1) in set(pages) for c in cites) or (
            expects and any(int(c.get("page") or -1) in set(pages) for c in cites)
        )
    elif not expects:
        out["each_cited_passage_supports_answer"] = True if not cites else None
    else:
        out["each_cited_passage_supports_answer"] = bool(cites) and enough
    return out


def ensure_book(engine, book_id: str, label: str, pdf: Path, chunks: Path) -> None:
    from pipeline import BOOKS
    from live_ingest import spine_from_label

    if book_id in BOOKS:
        BOOKS[book_id]["in_library"] = False
        return
    BOOKS[book_id] = {
        "label": label,
        "short_label": label,
        "spine": spine_from_label(label),
        "group": "experiment",
        "is_excerpt": False,
        "live": True,
        "in_library": False,
        "note": "OCR experiment index",
        "chunks": chunks,
        "pdf": pdf,
    }
    engine._load_book(book_id)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", type=Path, default=ROOT / "outputs" / "usgs_volcanoes_frozen_cases.json")
    ap.add_argument("--baseline-id", default="live_usgs_volcanoes_b2967ed2")
    ap.add_argument("--ocr-id", default="exp_usgs_volcanoes_ocr_v1")
    ap.add_argument("--with-sol", action="store_true")
    ap.add_argument(
        "--sol-case-ids",
        default="usgs_page21_photo_caption,usgs_page23_paricutin,usgs_page23_vesuvius,usgs_current_alert_unanswerable,usgs_four_types",
        help="Comma-separated case ids to send to Sol when --with-sol is set.",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=ROOT / "outputs" / "ocr_experiments" / "exp_usgs_volcanoes_ocr_v1" / "usgs_ocr_v1_comparison.json",
    )
    args = ap.parse_args()
    load_local_env()

    cases_doc = json.loads(args.cases.read_text(encoding="utf-8"))
    cases = cases_doc.get("cases") or []
    sol_ids = {s.strip() for s in (args.sol_case_ids or "").split(",") if s.strip()}

    from pipeline import DemoEngine

    print("Loading demo engine (models)…")
    engine = DemoEngine()
    exp_dir = ROOT / "outputs" / "ocr_experiments" / args.ocr_id
    ensure_book(
        engine,
        args.ocr_id,
        "USGS Volcanoes OCR experiment v1",
        exp_dir / "usgs-volcanoes.pdf",
        exp_dir / f"{args.ocr_id}_stage1_chunks.json",
    )
    # Baseline already restored from demo_uploads if present.
    if args.baseline_id not in engine._book:
        ensure_book(
            engine,
            args.baseline_id,
            "USGS Volcanoes baseline",
            ROOT / "demo_uploads" / f"{args.baseline_id}.pdf",
            ROOT / "demo_uploads" / f"{args.baseline_id}_stage1_chunks.json",
        )

    results = []
    estimated_usd = 0.0
    for case in cases:
        cid = case["id"]
        q = case["question"]
        row = {"id": cid, "question": q, "expects_answerable": case.get("expects_answerable"), "systems": {}}
        for book_id, tag in ((args.baseline_id, "baseline_text"), (args.ocr_id, "ocr_low_text_v1")):
            print(f"retrieve {tag} :: {cid}")
            retrieval = run_retrieval(engine, book_id, q)
            ask = None
            if args.with_sol and cid in sol_ids:
                print(f"sol {tag} :: {cid}")
                ask = run_ask(engine, book_id, q)
                estimated_usd += float(((ask.get("cost") or {}).get("estimated_usd")) or 0.0)
            row["systems"][tag] = {
                "book_id": book_id,
                "retrieval": retrieval,
                "ask": ask,
                "scores": score_case(case, retrieval, ask),
            }
        results.append(row)

    out = {
        "artifact": "usgs_ocr_v1_comparison",
        "created_at": utc_now(),
        "baseline_book_id": args.baseline_id,
        "ocr_book_id": args.ocr_id,
        "cases_file": str(args.cases),
        "with_sol": bool(args.with_sol),
        "sol_case_ids": sorted(sol_ids),
        "estimated_usd_this_run": round(estimated_usd, 6),
        "results": results,
        "notes": [
            "OCR text is experimental and may contain recognition errors (e.g. Heléns).",
            "Do not treat OCR snippets as verified quotations without checking the PDF page.",
            "NIST/Apollo regression scoring is separate if run.",
        ],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "out": str(args.out), "estimated_usd": out["estimated_usd_this_run"]}, indent=2))


if __name__ == "__main__":
    main()
