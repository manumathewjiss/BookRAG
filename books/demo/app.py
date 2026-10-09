"""Local BookRAG demo server. Bind to localhost only. Not a public deploy."""

from __future__ import annotations

import logging
import re
import sys
import time
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file
from werkzeug.exceptions import RequestEntityTooLarge

DEMO = Path(__file__).resolve().parent
ROOT = DEMO.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(DEMO) not in sys.path:
    sys.path.insert(0, str(DEMO))

from pipeline import (
    BOOKS,
    DEMO_MAX_PDF_BYTES,
    MAX_QUESTION_CHARS,
    MAX_REQUEST_BYTES,
    DemoEngine,
    DemoUserError,
    book_catalog,
    pdf_is_available,
)
from showcase_store import append_case, load_store

app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.config["MAX_CONTENT_LENGTH"] = DEMO_MAX_PDF_BYTES
app.jinja_env.auto_reload = True
_engine: DemoEngine | None = None
_startup_seconds: float | None = None

log = logging.getLogger("bookrag.demo")
if not log.handlers:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)

_SECRETISH_RE = re.compile(r"(?i)(sk-[A-Za-z0-9_\-]{8,}|api[_-]?key\s*[:=]\s*\S+)")


def engine() -> DemoEngine:
    global _engine, _startup_seconds
    if _engine is None:
        t0 = time.perf_counter()
        _engine = DemoEngine()
        _startup_seconds = float(getattr(_engine, "startup_seconds", None) or (time.perf_counter() - t0))
        print(f"Local models and book indexes loaded in {_startup_seconds:.1f}s (startup, not question wait)")
    return _engine


def _safe_log_exception(exc: BaseException, *, book_id: str, question_len: int) -> None:
    """Log type + short sanitized detail. Never log API keys or full prompts."""
    raw = str(exc) or type(exc).__name__
    safe = _SECRETISH_RE.sub("[redacted]", raw)
    if len(safe) > 240:
        safe = safe[:237] + "…"
    log.error(
        "ask failed book_id=%s question_chars=%s exc_type=%s detail=%s",
        book_id or "?",
        question_len,
        type(exc).__name__,
        safe,
    )


@app.get("/")
def index():
    return render_template(
        "index.html",
        books=[b for b in book_catalog() if b.get("in_library")],
        max_question_chars=MAX_QUESTION_CHARS,
    )


@app.get("/classic")
def classic():
    """Previous single-column demo UI, kept recoverable."""
    return render_template(
        "index_classic.html",
        books=[{"id": k, "label": v["label"]} for k, v in BOOKS.items()],
    )


@app.get("/pdf/<book_id>")
def pdf_file(book_id: str):
    """Serve the real sample or attached PDF for a catalog book. Localhost only."""
    rec = BOOKS.get(book_id) or {}
    path = rec.get("pdf")
    if not path or not pdf_is_available(book_id):
        return jsonify({"ok": False, "error": "PDF is not available for this book."}), 404
    resolved = Path(path).resolve()
    return send_file(
        resolved,
        mimetype="application/pdf",
        as_attachment=False,
        download_name=resolved.name,
        max_age=0,
    )


@app.post("/ask")
def ask():
    raw = request.get_data(cache=True, as_text=False) or b""
    if len(raw) > MAX_REQUEST_BYTES:
        return jsonify(
            {
                "ok": False,
                "error": "That request is too large for this local demo.",
            }
        ), 400
    body = request.get_json(silent=True) or {}
    book_id = (body.get("book_id") or "").strip()
    question = body.get("question") if isinstance(body.get("question"), str) else ""
    question_len = len(question or "")
    try:
        result = engine().ask(book_id, question)
    except DemoUserError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        _safe_log_exception(exc, book_id=book_id, question_len=question_len)
        return jsonify(
            {
                "ok": False,
                "error": "Something went wrong while answering. Check the local demo terminal for details.",
            }
        ), 500
    return jsonify({"ok": True, "result": result})


@app.get("/attach/status")
def attach_status():
    eng = engine()
    return jsonify({"ok": True, **eng.attach_status})


@app.post("/attach")
def attach():
    upload = request.files.get("file") or request.files.get("pdf")
    if upload is None or not (upload.filename or "").strip():
        return jsonify({"ok": False, "error": "Please choose a PDF to attach."}), 400
    name = Path(upload.filename).name
    if not name.lower().endswith(".pdf"):
        return jsonify({"ok": False, "error": "Please attach a PDF file."}), 400
    data = upload.read()
    try:
        result = engine().attach_pdf(data, name)
    except DemoUserError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        _safe_log_exception(exc, book_id="attach", question_len=len(data))
        return jsonify(
            {
                "ok": False,
                "error": "Could not index that PDF. Check the local demo terminal for details.",
            }
        ), 500
    return jsonify({"ok": True, "result": result, "catalog": book_catalog()})


@app.post("/detach")
def detach():
    payload = request.get_json(silent=True) or {}
    book_id = str(payload.get("book_id") or "").strip()
    if not book_id:
        return jsonify({"ok": False, "error": "Choose a book to remove."}), 400
    try:
        result = engine().detach_book(book_id)
    except DemoUserError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        _safe_log_exception(exc, book_id=book_id or "detach", question_len=0)
        return jsonify(
            {
                "ok": False,
                "error": "Could not remove that book. Check the local demo terminal for details.",
            }
        ), 500
    return jsonify({"ok": True, "result": result, "catalog": book_catalog()})


@app.get("/showcase")
def showcase_list():
    store = load_store()
    return jsonify(
        {
            "ok": True,
            "n_cases": store.get("n_cases", 0),
            "updated_at": store.get("updated_at"),
            "path": str((ROOT / "outputs" / "demo_showcase_cases.json").resolve()),
            "cases": store.get("cases") or [],
        }
    )


@app.post("/showcase/save")
def showcase_save():
    payload = request.get_json(silent=True) or {}
    result = payload.get("result")
    if not isinstance(result, dict):
        return jsonify({"ok": False, "error": "Ask a question first, then save that answer."}), 400
    index_seconds = payload.get("index_seconds")
    browser_wait_seconds = payload.get("browser_wait_seconds")
    note = payload.get("note") if isinstance(payload.get("note"), str) else ""
    try:
        index_val = float(index_seconds) if index_seconds is not None and index_seconds != "" else None
    except (TypeError, ValueError):
        index_val = None
    try:
        browser_val = (
            float(browser_wait_seconds) if browser_wait_seconds is not None and browser_wait_seconds != "" else None
        )
    except (TypeError, ValueError):
        browser_val = None
    try:
        saved = append_case(
            result,
            index_seconds=index_val,
            browser_wait_seconds=browser_val,
            note=note,
        )
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        _safe_log_exception(exc, book_id=str(result.get("book_id") or "showcase"), question_len=0)
        return jsonify({"ok": False, "error": "Could not save that showcase case."}), 500
    return jsonify({"ok": True, **saved})


@app.errorhandler(RequestEntityTooLarge)
def too_large(_exc):
    return jsonify({"ok": False, "error": "That PDF is too large for a live attach in this local demo."}), 413


@app.get("/ready")
def ready():
    eng = engine()
    return jsonify(
        {
            "ok": True,
            "startup_seconds": _startup_seconds or getattr(eng, "startup_seconds", None),
            "books": list(BOOKS.keys()),
            "catalog": book_catalog(),
            "budget": eng.budget_status(),
            "attach": eng.attach_status,
        }
    )


def main() -> None:
    print("BookRAG local demo: http://127.0.0.1:5055  (localhost only)")
    print("Previous UI remains at http://127.0.0.1:5055/classic")
    print("Loading local models now so the first question does not include startup wait…")
    engine()
    app.run(host="127.0.0.1", port=5055, debug=False, threaded=True)


if __name__ == "__main__":
    main()
