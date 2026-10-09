#!/usr/bin/env python3
"""Controlled low-text-page OCR experiment (does not change the live demo default).

General rule: pages whose ordinary extract has very few letters are OCR'd and
saved under a separate experimental book_id / artifact tree. Baseline files are
left untouched.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
OUT_ROOT = ROOT / "outputs" / "ocr_experiments"


def letter_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z]", text or ""))


def is_low_text_page(text: str, *, max_letters: int = 80) -> bool:
    """Book-independent rule: ordinary extract has too little alphabetic text."""
    return letter_count(text) < max_letters


def clean_ocr_text(text: str) -> str:
    t = text or ""
    t = t.replace("\u00ad", "")
    # Keep readable lines; drop ultra-short OCR speckles.
    lines = []
    for ln in t.splitlines():
        s = ln.strip()
        if not s:
            continue
        if letter_count(s) < 3 and not re.search(r"\d{3,}", s):
            continue
        lines.append(s)
    return "\n".join(lines).strip()


def ocr_page(pdf_path: Path, page: int, *, dpi: int = 200, psm: int = 6) -> str:
    from pdf2image import convert_from_path
    import pytesseract

    images = convert_from_path(str(pdf_path), first_page=page, last_page=page, dpi=dpi)
    if not images:
        return ""
    raw = pytesseract.image_to_string(images[0], config=f"--psm {psm}")
    return clean_ocr_text(raw)


def pages_from_chunks(chunks: list[dict]) -> dict[int, str]:
    by: dict[int, str] = defaultdict(str)
    for c in chunks:
        page = int(c.get("page") or 0)
        by[page] += "\n" + (c.get("text") or "")
    return {p: t.strip() for p, t in by.items()}


def build_experimental_payload(
    baseline: dict[str, Any],
    *,
    exp_book_id: str,
    pdf_path: Path,
    max_letters: int,
    dpi: int,
    psm: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    chunks = list(baseline.get("chunks") or [])
    by_page = pages_from_chunks(chunks)
    low_pages = sorted(p for p, t in by_page.items() if is_low_text_page(t, max_letters=max_letters))

    ocr_pages: dict[str, Any] = {}
    t_ocr = 0.0
    for page in low_pages:
        t0 = time.perf_counter()
        text = ocr_page(pdf_path, page, dpi=dpi, psm=psm)
        dt = time.perf_counter() - t0
        t_ocr += dt
        ocr_pages[str(page)] = {
            "page": page,
            "baseline_letters": letter_count(by_page.get(page, "")),
            "baseline_preview": (by_page.get(page, "") or "")[:120],
            "ocr_seconds": round(dt, 3),
            "ocr_letters": letter_count(text),
            "ocr_text": text,
            "source_kind": "ocr_low_text_page",
            "uncertainty_note": "Recognized from page image; treat as OCR text, not a verified quotation.",
        }

    # Rebuild chunks: keep non-low-text chunks; replace each low-text page with one OCR chunk.
    kept: list[dict[str, Any]] = []
    for c in chunks:
        page = int(c.get("page") or 0)
        if page in low_pages:
            continue
        kept.append(dict(c))

    for page in low_pages:
        rec = ocr_pages[str(page)]
        text = rec.get("ocr_text") or ""
        if letter_count(text) < 3:
            # Fall back to original extract if OCR failed badly.
            text = by_page.get(page, "") or ""
            rec["ocr_failed_kept_baseline"] = True
        kept.append(
            {
                "chunk_index": -1,
                "page": page,
                "text": text,
                "source_kind": "ocr_low_text_page",
                "ocr_uncertain": True,
            }
        )

    kept.sort(key=lambda r: (int(r.get("page") or 0), str(r.get("text") or "")[:20]))
    for i, rec in enumerate(kept):
        rec["chunk_index"] = i

    payload = dict(baseline)
    payload["book_id"] = exp_book_id
    payload["chunks"] = kept
    payload["chunk_count"] = len(kept)
    payload["experiment"] = {
        "name": "low_text_page_ocr_v1",
        "max_letters": max_letters,
        "dpi": dpi,
        "psm": psm,
        "low_text_pages": low_pages,
        "ocr_seconds_total": round(t_ocr, 3),
    }
    payload["filename"] = baseline.get("filename") or pdf_path.name
    report = {
        "exp_book_id": exp_book_id,
        "baseline_chunk_count": len(chunks),
        "experimental_chunk_count": len(kept),
        "low_text_pages": low_pages,
        "ocr_seconds_total": round(t_ocr, 3),
        "ocr_pages": ocr_pages,
        "control_text_pages_checked": [10, 16, 28],
        "note": "Only low-text pages were OCR-replaced; text-heavy pages kept baseline extract.",
    }
    return payload, report


def index_payload(payload: dict[str, Any], *, status_print: bool = True) -> dict[str, float]:
    import sys

    demo_dir = ROOT / "demo"
    if str(demo_dir) not in sys.path:
        sys.path.insert(0, str(demo_dir))
    from live_ingest import index_bge_m3_hybrid, store_chunks_without_e5
    from embed_bge_m3_dense import load_bge_m3, BGE_MODEL
    from bge_m3_sparse import BgeM3SparseEncoder

    def status(step: str, detail: str) -> None:
        if status_print:
            print(f"[{step}] {detail}")

    t0 = time.perf_counter()
    store_chunks_without_e5(payload)
    dense = load_bge_m3(BGE_MODEL, "cpu")
    sparse = BgeM3SparseEncoder(BGE_MODEL, device="cpu", max_length=512)
    times = index_bge_m3_hybrid(
        payload,
        dense_model=dense,
        sparse_encoder=sparse,
        status=status,
    )
    return {
        "store_and_embed_seconds": round(time.perf_counter() - t0, 3),
        "dense_s": round(float(times.get("dense_s") or 0.0), 3),
        "sparse_s": round(float(times.get("sparse_s") or 0.0), 3),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", type=Path, default=ROOT / "sample_pdfs" / "usgs-volcanoes.pdf")
    ap.add_argument(
        "--baseline-chunks",
        type=Path,
        default=ROOT / "demo_uploads" / "live_usgs_volcanoes_b2967ed2_stage1_chunks.json",
    )
    ap.add_argument("--exp-id", default="exp_usgs_volcanoes_ocr_v1")
    ap.add_argument("--max-letters", type=int, default=80)
    ap.add_argument("--dpi", type=int, default=200)
    ap.add_argument("--psm", type=int, default=6)
    ap.add_argument("--skip-index", action="store_true")
    args = ap.parse_args()

    if not shutil.which("tesseract"):
        raise SystemExit("tesseract not found on PATH; install local OCR first.")
    if not args.pdf.is_file():
        raise SystemExit(f"PDF missing: {args.pdf}")
    if not args.baseline_chunks.is_file():
        raise SystemExit(f"Baseline chunks missing: {args.baseline_chunks}")

    out_dir = OUT_ROOT / args.exp_id
    out_dir.mkdir(parents=True, exist_ok=True)

    baseline = json.loads(args.baseline_chunks.read_text(encoding="utf-8"))
    payload, report = build_experimental_payload(
        baseline,
        exp_book_id=args.exp_id,
        pdf_path=args.pdf,
        max_letters=args.max_letters,
        dpi=args.dpi,
        psm=args.psm,
    )

    chunks_path = out_dir / f"{args.exp_id}_stage1_chunks.json"
    report_path = out_dir / f"{args.exp_id}_ocr_report.json"
    # Copy PDF bytes into experiment folder for reviewability (do not touch sample_pdfs).
    exp_pdf = out_dir / args.pdf.name
    if not exp_pdf.exists():
        shutil.copy2(args.pdf, exp_pdf)

    chunks_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    index_times: dict[str, float] = {}
    if not args.skip_index:
        index_times = index_payload(payload)
    report["index_times"] = index_times
    report["artifacts"] = {
        "chunks": str(chunks_path),
        "pdf_copy": str(exp_pdf),
        "report": str(report_path),
    }
    # Manual caption check helpers for USGS page 21 (not a production rule).
    p21 = (report.get("ocr_pages") or {}).get("21") or {}
    report["manual_page21_check"] = {
        "ocr_preview": (p21.get("ocr_text") or "")[:240],
        "mentions_helens": bool(re.search(r"Helens|Hel[eé]ns", p21.get("ocr_text") or "", re.I)),
        "mentions_may_18": bool(re.search(r"May[,\s]*18", p21.get("ocr_text") or "", re.I)),
        "mentions_1980": "1980" in (p21.get("ocr_text") or ""),
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "report": str(report_path), **{k: report[k] for k in ("low_text_pages", "ocr_seconds_total", "index_times", "manual_page21_check")}}, indent=2))


if __name__ == "__main__":
    main()
