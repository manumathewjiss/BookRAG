"""
Local BookRAG demo pipeline: BGE-M3 hybrid top 20 → Qwen → Sol.

Not production. Does not change retrieve_stage3 defaults.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEMO = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(DEMO) not in sys.path:
    sys.path.insert(0, str(DEMO))

from bge_m3_sparse import BGE_MODEL, BgeM3SparseEncoder, build_sparse_index, reciprocal_rank_fusion, search_sparse
from db import connect, load_bge_m3_hybrid_sparse_corpus, search_chunks_bge_m3
from embed_bge_m3_dense import load_bge_m3
from evaluate_bge_m3_dense import embed_query
from evaluate_qwen3_reranker_0_6b_local import MODEL_ID as QWEN_ID, Qwen3Reranker, choose_device
from local_env import load_local_env, openai_api_key_configured
from sol_answer_common import (
    ANSWER_SCHEMA_WITH_ANSWER_SUPPORT,
    ANSWER_SUPPORT_INSTRUCTIONS,
    MODEL,
    REASONING_EFFORT,
    SERVICE_TIER,
    apply_event_match_gate,
    estimate_usd,
    reader_evidence_label,
    sanitize_citations,
)
from demo_retrieval_helpers import quoted_spans_supported_by_citations, select_supporting_excerpt

SAMPLE_PDFS = ROOT / "sample_pdfs"
DEMO_UPLOADS = ROOT / "demo_uploads"
LIBRARY_ACTIVE_PATH = DEMO_UPLOADS / "library_active.json"
RESERVED_BOOK_IDS = frozenset(
    {
        "bhagavad_gita",
        "arthashastra",
        "thinkpython",
        "frankenstein_1532610843_print",
        "pride_and_prejudice",
    }
)

BOOKS = {
    "bhagavad_gita": {
        "label": "Bhagavad-gītā As It Is",
        "short_label": "Bhagavad Gita",
        "spine": "BG",
        "group": "presentation",
        "is_excerpt": False,
        "chunks": ROOT / "outputs" / "bhagavad_gita_stage1_chunks.json",
        "pdf": SAMPLE_PDFS / "Bhagavad-gita_As_It_Is.pdf",
    },
    "arthashastra": {
        "label": "Arthashastra (Temple Library excerpt)",
        "short_label": "Arthashastra",
        "spine": "A",
        "group": "presentation",
        "is_excerpt": True,
        "note": "8-page Temple Library excerpt, not the full classical work",
        "chunks": ROOT / "outputs" / "arthashastra_stage1_chunks.json",
        "pdf": SAMPLE_PDFS / "arthashastra.pdf",
    },
    "thinkpython": {
        "label": "Think Python",
        "short_label": "Think Python",
        "spine": "TP",
        "group": "presentation",
        "is_excerpt": False,
        "chunks": ROOT / "outputs" / "thinkpython_stage1_chunks.json",
        "pdf": SAMPLE_PDFS / "thinkpython.pdf",
    },
    # Kept available so earlier demos stay recoverable.
    "frankenstein_1532610843_print": {
        "label": "Frankenstein (1818 print PDF)",
        "short_label": "Frankenstein",
        "spine": "F",
        "group": "also",
        "is_excerpt": False,
        "chunks": ROOT / "outputs" / "frankenstein_1532610843_print_stage1_chunks.json",
        "pdf": SAMPLE_PDFS / "Frankenstein-1532610843._print.pdf",
    },
    "pride_and_prejudice": {
        "label": "Pride and Prejudice",
        "short_label": "Pride and Prejudice",
        "spine": "P",
        "group": "also",
        "is_excerpt": False,
        "chunks": ROOT / "outputs" / "pride_and_prejudice_stage1_chunks.json",
        "pdf": SAMPLE_PDFS / "pride-and-prejudice.pdf",
    },
}


def _pdf_roots() -> tuple[Path, ...]:
    return (SAMPLE_PDFS.resolve(), DEMO_UPLOADS.resolve())


def pdf_is_available(book_id: str) -> bool:
    rec = BOOKS.get(book_id) or {}
    path = rec.get("pdf")
    if not path:
        return False
    try:
        resolved = Path(path).resolve()
    except OSError:
        return False
    if not resolved.is_file():
        return False
    for root in _pdf_roots():
        try:
            resolved.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def catalog_item(book_id: str) -> dict:
    rec = BOOKS[book_id]
    return {
        "id": book_id,
        "label": rec["label"],
        "short_label": rec.get("short_label") or rec["label"],
        "spine": rec.get("spine") or rec["label"][:2].upper(),
        "is_excerpt": bool(rec.get("is_excerpt")),
        "note": rec.get("note") or "",
        "group": rec.get("group") or "also",
        "pdf_available": pdf_is_available(book_id),
        "live": bool(rec.get("live")),
        "in_library": bool(rec.get("in_library")),
    }


def book_catalog() -> list[dict]:
    """UI metadata only. Does not change retrieval."""
    return [catalog_item(book_id) for book_id in BOOKS]

CANDIDATE_K = 30
HYBRID_K = 20
QWEN_TOP = 5
RRF_K = 60

# Local-demo request limits (not OpenAI account balance).
MIN_QUESTION_CHARS = int(os.environ.get("DEMO_MIN_QUESTION_CHARS", "8"))
MAX_QUESTION_CHARS = int(os.environ.get("DEMO_MAX_QUESTION_CHARS", "1200"))
MAX_REQUEST_BYTES = int(os.environ.get("DEMO_MAX_REQUEST_BYTES", "8192"))
# Session estimate guard; configurable. Do not treat as the OpenAI balance.
DEMO_MAX_CALLS = int(os.environ.get("DEMO_MAX_CALLS", "40"))
DEMO_MAX_USD = float(os.environ.get("DEMO_MAX_USD", "5.0"))
DEMO_MAX_PDF_BYTES = int(os.environ.get("DEMO_MAX_PDF_BYTES", str(25 * 1024 * 1024)))
DEMO_MAX_PDF_PAGES = int(os.environ.get("DEMO_MAX_PDF_PAGES", "2000"))
DEMO_MAX_LIVE_CHUNKS = int(os.environ.get("DEMO_MAX_LIVE_CHUNKS", "3000"))
ORCH_STEPS = (
    ("extract", "Extract text"),
    ("chunk", "Chunk passages"),
    ("store", "Store passages"),
    ("dense", "Embed with BGE-M3"),
    ("sparse", "Build hybrid index"),
    ("ready", "Ready to ask"),
)
ORCH_ALIAS = {
    "save": "extract",
    "tokenizer": "extract",
    "index": "ready",
}


def orchestration_view(
    current_step: str,
    *,
    state: str,
    detail: str,
    timings: dict | None = None,
    active_seconds: float | None = None,
) -> dict:
    """Fixed pipeline status for the demo UI. Not an LLM agent."""
    mapped = ORCH_ALIAS.get(current_step, current_step)
    ids = [sid for sid, _label in ORCH_STEPS]
    idx = ids.index(mapped) if mapped in ids else -1
    times = timings or {}
    stages = []
    for i, (sid, label) in enumerate(ORCH_STEPS):
        if state == "idle" and mapped == "ready":
            status = "done"
        elif state == "running" and idx >= 0:
            if i < idx:
                status = "done"
            elif i == idx:
                status = "active"
            else:
                status = "wait"
        else:
            status = "wait"
        rec = {"id": sid, "label": label, "status": status}
        if status == "done" and sid in times:
            rec["seconds"] = times[sid]
        elif status == "active" and active_seconds is not None:
            rec["seconds"] = active_seconds
        stages.append(rec)
    return {
        "state": state,
        "step": mapped,
        "detail": detail,
        "stages": stages,
        "timings_seconds": times,
        "kind": "fixed_pipeline",
    }


class DemoUserError(ValueError):
    """Safe, short message intended for the browser."""


class DemoEngine:
    def __init__(self) -> None:
        load_local_env()
        if not openai_api_key_configured():
            raise RuntimeError("OPENAI_API_KEY missing from gitignored books/.env")
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
        t0 = time.perf_counter()
        self.dense = load_bge_m3(BGE_MODEL, "cpu")
        self.sparse_encoder = BgeM3SparseEncoder(BGE_MODEL, device="cpu", max_length=512)
        device, dtype, reason = choose_device("mps")
        self.qwen = Qwen3Reranker(QWEN_ID, device=device, dtype=dtype)
        self.qwen_device_reason = reason
        self.qwen.score_pairs("warmup", ["warmup passage one.", "warmup passage two."], batch_size=2)
        from openai import OpenAI

        self.client = OpenAI()
        self._book: dict[str, dict] = {}
        for book_id in list(BOOKS):
            self._load_book(book_id)
        self._restore_live_uploads()
        self.startup_seconds = round(time.perf_counter() - t0, 3)
        self.session_calls = 0
        self.session_estimated_usd = 0.0
        self.max_calls = DEMO_MAX_CALLS
        self.max_usd = DEMO_MAX_USD
        self._lock = threading.Lock()
        self._e5_tokenizer = None
        self._attach_phase_times: dict[str, float] = {}
        self._attach_phase_id: str | None = None
        self._attach_phase_started: float | None = None
        self.attach_status = orchestration_view("", state="idle", detail="Attach a PDF to run the pipeline.")
        self._restore_library_active()

    def validate_question(self, book_id: str, question: str) -> tuple[str, str]:
        book_id = (book_id or "").strip()
        question = (question or "").strip()
        if book_id not in BOOKS:
            raise DemoUserError("Please choose a book from the list.")
        if not question:
            raise DemoUserError("Please enter a question.")
        if len(question) < MIN_QUESTION_CHARS:
            raise DemoUserError("Please ask a fuller question.")
        if len(question) > MAX_QUESTION_CHARS:
            raise DemoUserError("That question is too long for this local demo.")
        return book_id, question

    def check_budget(self) -> None:
        if self.session_calls >= self.max_calls:
            raise DemoUserError(
                "Local demo call limit reached for this session "
                f"({self.max_calls} questions). Estimated usage only — not your OpenAI balance."
            )
        if self.session_estimated_usd >= self.max_usd:
            raise DemoUserError(
                "Local demo estimated-spend limit reached for this session "
                f"(about ${self.max_usd:.2f}). This is a demo estimate, not your OpenAI account balance."
            )

    def budget_status(self) -> dict:
        return {
            "session_calls": self.session_calls,
            "session_estimated_usd": round(self.session_estimated_usd, 6),
            "max_calls": self.max_calls,
            "max_usd": self.max_usd,
            "note": "Local demo estimate guard only; not the OpenAI account balance.",
        }

    def _freeze_attach_phase(self) -> None:
        if self._attach_phase_id and self._attach_phase_started is not None:
            self._attach_phase_times[self._attach_phase_id] = round(
                time.perf_counter() - self._attach_phase_started, 3
            )
        self._attach_phase_id = None
        self._attach_phase_started = None

    def set_attach_status(self, step: str, detail: str, *, state: str = "running") -> None:
        now = time.perf_counter()
        mapped = ORCH_ALIAS.get(step, step)
        if state == "running":
            if self._attach_phase_started is None:
                self._attach_phase_id = mapped
                self._attach_phase_started = now
            elif mapped != self._attach_phase_id and self._attach_phase_id:
                self._attach_phase_times[self._attach_phase_id] = round(now - self._attach_phase_started, 3)
                self._attach_phase_id = mapped
                self._attach_phase_started = now
        elif state == "idle" and mapped == "ready" and self._attach_phase_started is not None and self._attach_phase_id:
            self._attach_phase_times[self._attach_phase_id] = round(now - self._attach_phase_started, 3)
            self._attach_phase_id = None
            self._attach_phase_started = None
        active_seconds = None
        if state == "running" and self._attach_phase_started is not None:
            active_seconds = round(now - self._attach_phase_started, 1)
        self.attach_status = orchestration_view(
            step,
            state=state,
            detail=detail,
            timings=dict(self._attach_phase_times),
            active_seconds=active_seconds,
        )

    def attach_pdf(self, pdf_bytes: bytes, original_name: str) -> dict:
        """Chunk, index, and load a new PDF. Same hybrid search the demo already uses."""
        from live_ingest import (
            chunk_digital_pdf,
            index_bge_m3_hybrid,
            make_live_book_id,
            short_label_from_filename,
            spine_from_label,
            store_chunks_without_e5,
        )
        from chunking import load_e5_tokenizer

        if len(pdf_bytes) < 8 or not pdf_bytes.startswith(b"%PDF"):
            raise DemoUserError("Please attach a PDF file.")
        if len(pdf_bytes) > DEMO_MAX_PDF_BYTES:
            raise DemoUserError("That PDF is too large for a live attach in this local demo.")
        if not self._lock.acquire(blocking=False):
            raise DemoUserError("Wait until the current question or attach finishes.")
        book_id = None
        t0 = time.perf_counter()
        self._attach_phase_times = {}
        self._attach_phase_id = None
        self._attach_phase_started = None
        try:
            self.set_attach_status("save", "Saving the PDF locally…")
            DEMO_UPLOADS.mkdir(parents=True, exist_ok=True)
            # Only reserved/preloaded IDs are blocked. Existing live IDs for the same
            # PDF bytes must stay stable so we can reuse the index instead of renaming.
            book_id = make_live_book_id(original_name, pdf_bytes, set(RESERVED_BOOK_IDS))
            if book_id in RESERVED_BOOK_IDS or book_id in {
                k for k, v in BOOKS.items() if not v.get("live")
            }:
                raise DemoUserError("That book is already in the reserved library.")
            pdf_path = (DEMO_UPLOADS / f"{book_id}.pdf").resolve()
            pdf_path.relative_to(DEMO_UPLOADS.resolve())
            pdf_path.write_bytes(pdf_bytes)

            reused = self._try_reuse_existing_index(book_id, original_name=original_name, pdf_path=pdf_path)
            if reused is not None:
                elapsed = round(time.perf_counter() - t0, 3)
                reused["timings_seconds"] = dict(reused.get("timings_seconds") or {})
                reused["timings_seconds"]["reuse_attach"] = elapsed
                # Keep the original one-time indexing total for UI honesty.
                if reused["timings_seconds"].get("total") is None:
                    reused["timings_seconds"]["total"] = elapsed
                if isinstance(self.attach_status, dict):
                    times = dict(self.attach_status.get("timings_seconds") or {})
                    times["reuse_attach"] = elapsed
                    if times.get("total") is None:
                        times["total"] = reused["timings_seconds"].get("total")
                    self.attach_status["timings_seconds"] = times
                    self.attach_status["reused_existing_index"] = True
                self._persist_library_active(book_id, reused)
                return reused

            if self._e5_tokenizer is None:
                self.set_attach_status("tokenizer", "Loading the chunk tokenizer…")
                self._e5_tokenizer = load_e5_tokenizer()

            payload = chunk_digital_pdf(
                pdf_path,
                book_id=book_id,
                original_name=Path(original_name).name,
                tokenizer=self._e5_tokenizer,
                max_pages=DEMO_MAX_PDF_PAGES,
                max_chunks=DEMO_MAX_LIVE_CHUNKS,
                status=lambda step, detail: self.set_attach_status(step, detail),
            )
            (DEMO_UPLOADS / f"{book_id}_stage1_chunks.json").write_text(
                json.dumps(payload, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            self.set_attach_status("store", "Storing passages…")
            store_chunks_without_e5(payload)
            embed_times = index_bge_m3_hybrid(
                payload,
                dense_model=self.dense,
                sparse_encoder=self.sparse_encoder,
                status=lambda step, detail: self.set_attach_status(step, detail),
            )
            self.set_attach_status("index", "Loading the book into search…")
            label = short_label_from_filename(original_name)
            self._register_live_book(
                book_id,
                label=label,
                pdf_path=pdf_path,
                chunks_path=DEMO_UPLOADS / f"{book_id}_stage1_chunks.json",
            )
            elapsed = round(time.perf_counter() - t0, 3)
            self._attach_phase_times["total"] = elapsed
            detail = (
                f"Indexed {payload['chunk_count']} passages from {payload.get('total_pages')} PDF pages."
            )
            self.set_attach_status("ready", detail, state="idle")
            phase = dict(self._attach_phase_times)
            result = {
                "book": catalog_item(book_id),
                "book_id": book_id,
                "chunk_count": payload["chunk_count"],
                "total_pages": payload.get("total_pages"),
                "pages_with_text": payload.get("pages_with_extractable_text"),
                "timings_seconds": {
                    "extract": phase.get("extract"),
                    "chunk": phase.get("chunk"),
                    "store": phase.get("store"),
                    "dense": phase.get("dense", round(embed_times["dense_s"], 3)),
                    "sparse": phase.get("sparse", round(embed_times["sparse_s"], 3)),
                    "ready": phase.get("ready"),
                    "total": elapsed,
                },
                "reused_existing_index": False,
                "retrieval_method": "baseline_hybrid20_qwen5",
                "note": "Same hybrid search as the other books. E5 Stage 2 was not re-run.",
                "detail": detail,
            }
            if isinstance(self.attach_status, dict):
                self.attach_status["reused_existing_index"] = False
            self._persist_library_active(book_id, result)
            return result
        except DemoUserError:
            self._freeze_attach_phase()
            self.set_attach_status("idle", "Attach did not finish.", state="idle")
            raise
        except ValueError as exc:
            self._freeze_attach_phase()
            self.set_attach_status("idle", str(exc), state="idle")
            raise DemoUserError(str(exc)) from exc
        except Exception:
            self._freeze_attach_phase()
            self.set_attach_status(
                "idle",
                "Could not index that PDF. Check the local demo terminal.",
                state="idle",
            )
            raise
        finally:
            self._lock.release()

    def _load_book(self, book_id: str) -> dict:
        if book_id in self._book:
            return self._book[book_id]
        conn = connect()
        try:
            corpus = load_bge_m3_hybrid_sparse_corpus(conn, book_id)
        finally:
            conn.close()
        if not corpus:
            raise RuntimeError(f"No hybrid sparse rows for {book_id}")
        by_id = {int(c["chunk_index"]): c for c in corpus}
        self._book[book_id] = {
            "corpus": corpus,
            "index": build_sparse_index(corpus),
            "by_id": by_id,
        }
        return self._book[book_id]

    def _register_live_book(
        self,
        book_id: str,
        *,
        label: str,
        pdf_path: Path,
        chunks_path: Path | None,
    ) -> None:
        from live_ingest import spine_from_label

        self._clear_library_slot(except_id=book_id)
        BOOKS[book_id] = {
            "label": label,
            "short_label": label,
            "spine": spine_from_label(label),
            "group": "live",
            "is_excerpt": False,
            "live": True,
            "in_library": True,
            "note": "Attached in this demo session",
            "chunks": chunks_path,
            "pdf": pdf_path,
        }
        self._book.pop(book_id, None)
        self._load_book(book_id)

    def _try_reuse_existing_index(
        self,
        book_id: str,
        *,
        original_name: str,
        pdf_path: Path,
    ) -> dict | None:
        """If this exact PDF was already indexed, attach without re-embedding."""
        from live_ingest import short_label_from_filename

        chunks_path = DEMO_UPLOADS / f"{book_id}_stage1_chunks.json"
        if not chunks_path.is_file():
            return None
        conn = connect()
        try:
            corpus = load_bge_m3_hybrid_sparse_corpus(conn, book_id)
        finally:
            conn.close()
        if not corpus:
            return None
        try:
            payload = json.loads(chunks_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        chunk_count = int(payload.get("chunk_count") or len(payload.get("chunks") or []) or len(corpus))
        if chunk_count <= 0 or abs(chunk_count - len(corpus)) > max(2, chunk_count // 50):
            return None

        prior = self._read_attach_meta(book_id) or {}
        prior_timings = prior.get("timings_seconds") if isinstance(prior.get("timings_seconds"), dict) else {}
        label = short_label_from_filename(original_name)
        if payload.get("filename"):
            label = short_label_from_filename(str(payload["filename"]))

        self.set_attach_status("index", "Reusing the existing index for this exact PDF…")
        # Replay prior stage times so reload shows the original one-time indexing work.
        self._attach_phase_times = {
            k: float(v)
            for k, v in prior_timings.items()
            if k in {"extract", "chunk", "store", "dense", "sparse", "ready", "total"} and v is not None
        }
        self._register_live_book(book_id, label=label, pdf_path=pdf_path, chunks_path=chunks_path)
        detail = (
            f"Reused existing index: {chunk_count} passages from "
            f"{payload.get('total_pages')} PDF pages (no re-embed)."
        )
        self.set_attach_status("ready", detail, state="idle")
        # Mark reuse on the live attach_status so /ready can restore UI labels.
        if isinstance(self.attach_status, dict):
            self.attach_status["reused_existing_index"] = True
        return {
            "book": catalog_item(book_id),
            "book_id": book_id,
            "chunk_count": chunk_count,
            "total_pages": payload.get("total_pages"),
            "pages_with_text": payload.get("pages_with_extractable_text"),
            "timings_seconds": {
                "extract": prior_timings.get("extract"),
                "chunk": prior_timings.get("chunk"),
                "store": prior_timings.get("store"),
                "dense": prior_timings.get("dense"),
                "sparse": prior_timings.get("sparse"),
                "ready": prior_timings.get("ready"),
                "total": prior_timings.get("total"),
            },
            "reused_existing_index": True,
            "retrieval_method": "baseline_hybrid20_qwen5",
            "note": "Exact PDF already indexed on this machine; skipped BGE-M3 rebuild.",
            "detail": detail,
        }

    def _attach_meta_path(self, book_id: str) -> Path:
        return DEMO_UPLOADS / f"{book_id}_attach_meta.json"

    def _read_attach_meta(self, book_id: str) -> dict | None:
        path = self._attach_meta_path(book_id)
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return data if isinstance(data, dict) else None

    def _persist_library_active(self, book_id: str, result: dict) -> None:
        """Save active desk book + one-time indexing timings for page reload / restart."""
        DEMO_UPLOADS.mkdir(parents=True, exist_ok=True)
        timings = result.get("timings_seconds") if isinstance(result.get("timings_seconds"), dict) else {}
        record = {
            "book_id": book_id,
            "book_label": (BOOKS.get(book_id) or {}).get("label") or book_id,
            "chunk_count": result.get("chunk_count"),
            "total_pages": result.get("total_pages"),
            "detail": result.get("detail")
            or (
                f"Indexed {result.get('chunk_count')} passages from "
                f"{result.get('total_pages')} PDF pages."
            ),
            "timings_seconds": timings,
            "reused_existing_index": bool(result.get("reused_existing_index")),
            "saved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        try:
            self._attach_meta_path(book_id).write_text(
                json.dumps(record, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            LIBRARY_ACTIVE_PATH.write_text(
                json.dumps(record, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except OSError:
            pass

    def _clear_library_active_file(self) -> None:
        try:
            if LIBRARY_ACTIVE_PATH.is_file():
                LIBRARY_ACTIVE_PATH.unlink()
        except OSError:
            pass

    def _apply_attach_status_from_record(self, record: dict) -> None:
        timings = record.get("timings_seconds") if isinstance(record.get("timings_seconds"), dict) else {}
        self._attach_phase_times = {
            k: float(v)
            for k, v in timings.items()
            if isinstance(v, (int, float))
            and k in {"extract", "chunk", "store", "dense", "sparse", "ready", "total", "reuse_attach"}
        }
        detail = str(record.get("detail") or "Ready. Indexed book is attached.")
        self.set_attach_status("ready", detail, state="idle")
        if isinstance(self.attach_status, dict):
            # After restart/reload, keep historical reuse_attach for labels, but mark
            # restored so the UI does not claim the user just waited through a re-attach.
            self.attach_status["reused_existing_index"] = bool(record.get("reused_existing_index"))
            self.attach_status["restored_from_disk"] = True
            times = dict(self.attach_status.get("timings_seconds") or {})
            if isinstance(timings.get("reuse_attach"), (int, float)):
                times["reuse_attach"] = float(timings["reuse_attach"])
            self.attach_status["timings_seconds"] = times

    def _restore_library_active(self) -> None:
        """After live uploads load, restore the last attached desk book + pipeline timings."""
        if not LIBRARY_ACTIVE_PATH.is_file():
            return
        try:
            record = json.loads(LIBRARY_ACTIVE_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(record, dict):
            return
        book_id = str(record.get("book_id") or "").strip()
        if not book_id or book_id not in BOOKS or not BOOKS[book_id].get("live"):
            return
        self._clear_library_slot(except_id=book_id)
        BOOKS[book_id]["in_library"] = True
        BOOKS[book_id]["note"] = "Attached (restored after reload)"
        # Prefer per-book meta if present (more complete).
        meta = self._read_attach_meta(book_id) or record
        self._apply_attach_status_from_record(meta)

    def _restore_live_uploads(self) -> None:
        """Reload live-attached books already indexed on this machine. Does not re-embed."""
        from live_ingest import short_label_from_filename, spine_from_label

        if not DEMO_UPLOADS.is_dir():
            return
        for pdf in sorted(DEMO_UPLOADS.glob("live_*.pdf")):
            book_id = pdf.stem
            if book_id in BOOKS or book_id in RESERVED_BOOK_IDS:
                continue
            conn = connect()
            try:
                corpus = load_bge_m3_hybrid_sparse_corpus(conn, book_id)
            finally:
                conn.close()
            if not corpus:
                continue
            label = short_label_from_filename(book_id.replace("live_", "", 1))
            meta_path = DEMO_UPLOADS / f"{book_id}_stage1_chunks.json"
            if meta_path.is_file():
                try:
                    payload = json.loads(meta_path.read_text(encoding="utf-8"))
                    if payload.get("filename"):
                        label = short_label_from_filename(str(payload["filename"]))
                except Exception:
                    pass
            BOOKS[book_id] = {
                "label": label,
                "short_label": label,
                "spine": spine_from_label(label),
                "group": "live",
                "is_excerpt": False,
                "live": True,
                "in_library": False,
                "note": "Indexed earlier on this machine; not on the desk until attached",
                "chunks": meta_path if meta_path.is_file() else None,
                "pdf": pdf,
            }
            self._load_book(book_id)

    def _clear_library_slot(self, *, except_id: str | None = None) -> None:
        """Ensure at most one live book is marked attached in the library."""
        for bid, rec in list(BOOKS.items()):
            if except_id and bid == except_id:
                continue
            if not rec.get("live"):
                continue
            rec["in_library"] = False

    def detach_book(self, book_id: str) -> dict:
        """Remove the book from the professor desk. Keeps indexed files/DB rows for reuse."""
        book_id = (book_id or "").strip()
        rec = BOOKS.get(book_id)
        if not rec or not rec.get("live"):
            raise DemoUserError("Only an attached PDF can be removed.")
        if not self._lock.acquire(blocking=False):
            raise DemoUserError("Wait until the current question or attach finishes.")
        try:
            rec["in_library"] = False
            rec["note"] = "Indexed earlier on this machine; not on the desk until attached"
            self._clear_library_active_file()
            self._attach_phase_times = {}
            self.set_attach_status("idle", "Book removed from the desk. Attach a PDF to run the pipeline.", state="idle")
            return {"removed": book_id, "catalog": [c for c in book_catalog() if c.get("in_library")]}
        finally:
            self._lock.release()

    def retrieve_top5(self, book_id: str, question: str) -> dict:
        """Hybrid top-20 then Qwen top-5. No Sol call."""
        book_id, question = self.validate_question(book_id, question)
        pack = self._load_book(book_id)
        t0 = time.perf_counter()
        qvec, _ = embed_query(self.dense, question, device="cpu")
        q_sparse = self.sparse_encoder.encode_lexical_weights([question], batch_size=1)[0]
        conn = connect()
        try:
            dense_hits = search_chunks_bge_m3(conn, book_id=book_id, query_embedding=qvec.tolist(), top_k=CANDIDATE_K)
        finally:
            conn.close()
        sparse_hits = search_sparse(query_weights=q_sparse, corpus=pack["corpus"], index=pack["index"], top_k=CANDIDATE_K)
        fused = reciprocal_rank_fusion(
            [[h["chunk_index"] for h in dense_hits], [h["chunk_index"] for h in sparse_hits]],
            rrf_k=RRF_K,
            top_k=HYBRID_K,
        )
        hybrid = []
        for item in fused:
            row = pack["by_id"][item["chunk_index"]]
            hybrid.append(
                {
                    "passage_id": int(item["chunk_index"]),
                    "page": row.get("page"),
                    "text": row["text"],
                    "rrf_rank": item["rank"],
                }
            )
        retrieve_s = time.perf_counter() - t0
        t1 = time.perf_counter()
        scores = self.qwen.score_pairs(question, [h["text"] for h in hybrid], batch_size=2)
        ranked = sorted(zip(hybrid, scores), key=lambda x: (-x[1], x[0]["passage_id"]))
        top = []
        for rec, sc in ranked[:QWEN_TOP]:
            item = dict(rec)
            item["qwen_score"] = float(sc)
            top.append(item)
        qwen_s = time.perf_counter() - t1
        return {
            "hybrid": hybrid,
            "top": top,
            "retrieve_s": retrieve_s,
            "qwen_s": qwen_s,
        }

    def ask(self, book_id: str, question: str) -> dict:
        if not self._lock.acquire(blocking=False):
            raise DemoUserError("Wait until the current question or attach finishes.")
        try:
            return self._ask_locked(book_id, question)
        finally:
            self._lock.release()

    def _ask_locked(self, book_id: str, question: str) -> dict:
        book_id, question = self.validate_question(book_id, question)
        self.check_budget()
        t_all = time.perf_counter()
        ranked = self.retrieve_top5(book_id, question)
        hybrid = ranked["hybrid"]
        top = ranked["top"]
        retrieve_s = ranked["retrieve_s"]
        qwen_s = ranked["qwen_s"]

        t2 = time.perf_counter()
        passage_block = "\n\n".join(f"[passage_id={p['passage_id']}]\n{p['text']}" for p in top)
        user_msg = f"Question:\n{question}\n\nPassages (use only these; cite passage_id values):\n{passage_block}"
        resp = self.client.responses.create(
            model=MODEL,
            service_tier=SERVICE_TIER,
            store=False,
            reasoning={"effort": REASONING_EFFORT},
            instructions=ANSWER_SUPPORT_INSTRUCTIONS,
            input=user_msg,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "bookrag_grounded_answer_support",
                    "strict": True,
                    "schema": ANSWER_SCHEMA_WITH_ANSWER_SUPPORT,
                }
            },
        )
        sol_s = time.perf_counter() - t2
        parsed = apply_event_match_gate(json.loads((resp.output_text or "").strip()))
        usage = resp.usage.model_dump() if hasattr(resp.usage, "model_dump") else {}
        cost = estimate_usd(usage if isinstance(usage, dict) else {})
        self.session_calls += 1
        self.session_estimated_usd += float(cost.get("estimated_usd") or 0.0)
        sent = [{"passage_id": p["passage_id"], "page": p["page"], "text": p["text"]} for p in top]
        gate = sanitize_citations([int(i) for i in parsed.get("supporting_passage_ids") or []], sent)
        by_id = {p["passage_id"]: p for p in top}
        supporting = []
        for c in gate["display_citations"]:
            rec = by_id[c["passage_id"]]
            supporting.append(
                {
                    "passage_id": c["passage_id"],
                    "page": c["page"],
                    "text": rec["text"],
                    "qwen_score": rec.get("qwen_score"),
                }
            )
        enough = bool(parsed.get("enough_evidence")) and bool(supporting)
        quote_check = quoted_spans_supported_by_citations(
            parsed.get("answer") or "",
            [p["text"] for p in supporting],
        )
        # Quoted words must appear in a cited passage text, not merely share an ID.
        if quote_check["asks_or_uses_quotes"] and not quote_check["all_supported"]:
            enough = False
        evidence_label = reader_evidence_label(str(parsed.get("event_match") or ""), enough, len(supporting))
        if quote_check["asks_or_uses_quotes"] and not quote_check["all_supported"]:
            evidence_label = "Related passage only"
        answer_text = (
            parsed.get("answer")
            if enough
            else (
                parsed.get("answer")
                or parsed.get("missing_evidence")
                or "The retrieved passages do not contain enough evidence to answer."
            )
        )
        if quote_check["asks_or_uses_quotes"] and not quote_check["all_supported"] and answer_text:
            answer_text = (
                (answer_text or "").rstrip()
                + " The quoted wording above could not be fully verified in the cited passage text."
            )
        display_passages = []
        any_unreliable = False
        for p in supporting:
            picked = select_supporting_excerpt(
                p["text"],
                answer_text or "",
                question=question,
                claim_enough_evidence=enough,
            )
            if enough and not picked.get("excerpt_reliable"):
                any_unreliable = True
            display_passages.append(
                {
                    "passage_id": p["passage_id"],
                    "page": p["page"],
                    "page_label": "PDF page",
                    "excerpt": picked.get("excerpt") or "",
                    "excerpt_reliable": bool(picked.get("excerpt_reliable")),
                    "excerpt_anchor": picked.get("excerpt_anchor"),
                    "excerpt_note": picked.get("excerpt_note") or "",
                    "text": p["text"],
                    "qwen_score": p.get("qwen_score"),
                }
            )
        if enough and any_unreliable:
            # Do not present a short start-snippet as proof when the window missed.
            evidence_label = (
                "Answer claims support; inspect the full passage "
                "(short excerpt could not isolate the supporting sentence)"
            )
        total_s = time.perf_counter() - t_all
        return {
            "book_id": book_id,
            "book_label": BOOKS[book_id]["label"],
            "question": question,
            "answer": answer_text,
            "enough_evidence": enough,
            "evidence_label": evidence_label,
            "missing_evidence": parsed.get("missing_evidence") or "",
            "citations": [
                {
                    **c,
                    "page_label": "PDF page",
                }
                for c in gate["display_citations"]
            ],
            "rejected_citations": gate["rejected_citations"],
            "supporting_passages": display_passages,
            "quote_check": {
                "all_supported": quote_check["all_supported"],
                "asks_or_uses_quotes": quote_check["asks_or_uses_quotes"],
                "unsupported_count": len(quote_check.get("unsupported") or []),
                "note": quote_check["note"],
            },
            "hybrid_pool20_ids": [h["passage_id"] for h in hybrid],
            "qwen_top5_ids": [p["passage_id"] for p in top],
            "timings_seconds": {
                "retrieve_hybrid": round(retrieve_s, 3),
                "qwen_rerank": round(qwen_s, 3),
                "sol_api": round(sol_s, 3),
                "total_wait": round(total_s, 3),
            },
            "cost": cost,
            "budget": self.budget_status(),
            "instruction": "answer_support_direct_or_later_explanation",
            "retrieval_method": "baseline_hybrid20_qwen5",
            "asked_event": parsed.get("asked_event") or "",
            "event_match": parsed.get("event_match") or "",
            "startup_seconds_already_paid": getattr(self, "startup_seconds", None),
            "qwen_device": self.qwen_device_reason,
            "pdf_available": pdf_is_available(book_id),
        }
