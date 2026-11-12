from __future__ import annotations

import hashlib
import io
import logging
import time
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from psycopg import Error as DatabaseError
from pypdf import PdfReader, PdfWriter

from .config import settings
from .providers import HostedModels, ProviderError, ProviderUncertainCharge
from .question_match import ANSWER_PIPELINE_VERSION, canonicalize_question, question_signature
from .repository import AnswerBusy, Repository, UsageLimitReached
from .retrieval import bm25_top, fuse
from .schemas import Answer, ChatRequest, Citation, Document, Timings, Usage
from .security import verify_access_token
from .storage import PrivateStorage, StorageError


def _citations_from_saved(raw) -> list[Citation]:
    rows = raw if isinstance(raw, list) else []
    return [Citation.model_validate(item) for item in rows]


def _find_exact_saved_answer(repo: Repository, owner: UUID, document_id: UUID, question: str,
                             document_sha256: str) -> dict | None:
    """Indexed lookup of the strict canonical key. No scan and no model call."""
    return repo.find_exact_saved_answer(
        owner, document_id, canonicalize_question(question), document_sha256, ANSWER_PIPELINE_VERSION,
    )


def _usage_from_provider(usage: dict | None) -> tuple[int, int]:
    raw = usage or {}
    inp = int(raw.get("input_tokens") or raw.get("prompt_tokens") or 0)
    out = int(raw.get("output_tokens") or raw.get("completion_tokens") or 0)
    return inp, out


def _estimate_usd(embed_tokens: int, rerank_tokens: int, input_tokens: int, output_tokens: int) -> float:
    return round((embed_tokens * .12 + rerank_tokens * .05 + input_tokens * 2 + output_tokens * 10) / 1_000_000, 6)


def _answer_from_saved(row: dict, *, reused: bool, search_ms: int = 0, rerank_ms: int = 0,
                       answer_ms: int = 0, usage: Usage | None = None) -> Answer:
    return Answer(
        answer=row["answer_text"],
        enough_evidence=bool(row["enough_evidence"]),
        evidence_status=row["evidence_status"],
        citations=_citations_from_saved(row["citations"]),
        timings_ms=Timings(search=search_ms, rerank=rerank_ms, answer=answer_ms),
        usage=usage or Usage(),
        reused_answer=reused,
    )


def get_repo() -> Repository:
    return Repository(settings().database_url)


def get_storage() -> PrivateStorage:
    return PrivateStorage(settings())


def get_models() -> HostedModels:
    return HostedModels(settings())


def _sample_id() -> UUID | None:
    configured = settings().guest_sample_document_id.strip()
    expected_digest = settings().guest_sample_sha256.strip().lower()
    if not configured or len(expected_digest) != 64 or any(ch not in "0123456789abcdef" for ch in expected_digest):
        return None
    try:
        return UUID(configured)
    except ValueError:
        logger.error("Invalid GUEST_SAMPLE_DOCUMENT_ID; shared sample disabled")
        return None


def _approved_sample(row: dict) -> bool:
    return row["sha256"].lower() == settings().guest_sample_sha256.strip().lower()


def _readable_document(repo: Repository, owner: UUID, document_id: UUID) -> dict | None:
    """Private document first; only one explicitly configured sample is shared."""
    row = repo.document(owner, document_id)
    if row:
        return dict(row, is_sample=False)
    if document_id == _sample_id():
        sample = repo.ready_sample_document(document_id)
        if sample and _approved_sample(sample):
            return dict(sample, is_sample=True)
    return None


app = FastAPI(title="BookRAG Cloud API", version="1.0.0", docs_url="/api/v1/docs", openapi_url="/api/v1/openapi.json")
logger = logging.getLogger(__name__)
app.add_middleware(CORSMiddleware, allow_origins=settings().origins(), allow_credentials=False,
                   allow_methods=["GET", "POST", "DELETE"], allow_headers=["Authorization", "Content-Type"])


@app.middleware("http")
async def reject_large_declared_upload(request: Request, call_next):
    if request.method == "POST" and request.url.path == "/api/v1/documents":
        declared = request.headers.get("content-length")
        if declared:
            try:
                if int(declared) > settings().max_pdf_bytes + 64 * 1024:
                    return JSONResponse(status_code=413, content={"error": {"code": "http_413", "message": "PDF is too large"}})
            except ValueError:
                return JSONResponse(status_code=400, content={"error": {"code": "invalid_request", "message": "Invalid request length"}})
    return await call_next(request)


@app.exception_handler(HTTPException)
async def http_error(_request: Request, exc: HTTPException):
    message = exc.detail if isinstance(exc.detail, str) else "Request failed"
    return JSONResponse(status_code=exc.status_code, content={"error": {"code": f"http_{exc.status_code}", "message": message}})


@app.exception_handler(RequestValidationError)
async def validation_error(_request: Request, _exc: RequestValidationError):
    return JSONResponse(status_code=400, content={"error": {"code": "invalid_request", "message": "Please check the request fields"}})


@app.get("/api/v1/health")
def health():
    return {"status": "ok"}


@app.get("/api/v1/me")
def me(owner: UUID = Depends(verify_access_token), repo: Repository = Depends(get_repo)):
    return {"user_id": owner, "daily_questions_used": repo.count_today(owner, "question"),
            "daily_uploads_used": repo.count_today(owner, "upload")}


@app.post("/api/v1/documents", status_code=202)
async def upload_document(file: UploadFile = File(...), title: str | None = Form(None),
                          owner: UUID = Depends(verify_access_token), repo: Repository = Depends(get_repo),
                          storage: PrivateStorage = Depends(get_storage)):
    cfg = settings()
    if repo.count_today(owner, "upload") >= cfg.daily_upload_limit:
        raise HTTPException(429, "Daily PDF upload limit reached")
    name = (file.filename or "document.pdf").split("/")[-1].split("\\")[-1]
    name = "".join(ch for ch in name if ch.isprintable()).strip()[:255]
    if not name.lower().endswith(".pdf"):
        raise HTTPException(400, "Choose a PDF file")
    data = await file.read(cfg.max_pdf_bytes + 1)
    if len(data) > cfg.max_pdf_bytes:
        raise HTTPException(413, "PDF is too large")
    if not data.startswith(b"%PDF-"):
        raise HTTPException(400, "File is not a valid PDF")
    document_id = uuid4()
    path = f"{owner}/{document_id}/source.pdf"
    safe_title = "".join(ch for ch in (title or name[:-4]) if ch.isprintable()).strip()[:180]
    if not safe_title:
        raise HTTPException(400, "A title is required")
    try:
        storage.upload(path, data)
        row = repo.create_document(owner, document_id, safe_title, name[:255], path,
                                   hashlib.sha256(data).hexdigest(), cfg.daily_upload_limit)
    except StorageError:
        raise HTTPException(503, "PDF storage is temporarily unavailable") from None
    except UsageLimitReached:
        try:
            storage.delete(path)
        except StorageError:
            pass
        raise HTTPException(429, "Daily PDF upload limit reached") from None
    except Exception:
        try:
            storage.delete(path)
        except StorageError:
            pass  # Private orphan can be cleaned by an operator; never expose it to another user.
        raise
    return {"document": Document.model_validate(row)}


@app.get("/api/v1/documents")
def list_documents(owner: UUID = Depends(verify_access_token), repo: Repository = Depends(get_repo)):
    rows = [dict(row, is_sample=False) for row in repo.list_documents(owner)]
    sample_id = _sample_id()
    if sample_id and not any(row["id"] == sample_id for row in rows):
        sample = repo.ready_sample_document(sample_id)
        if sample and _approved_sample(sample):
            rows.insert(0, dict(sample, is_sample=True))
    return {"documents": [Document.model_validate(row) for row in rows]}


@app.get("/api/v1/documents/{document_id}")
def get_document(document_id: UUID, owner: UUID = Depends(verify_access_token), repo: Repository = Depends(get_repo)):
    row = _readable_document(repo, owner, document_id)
    if not row:
        raise HTTPException(404, "Document not found")
    return {"document": Document.model_validate(row)}


@app.get("/api/v1/documents/{document_id}/pdf")
def get_document_pdf(document_id: UUID, owner: UUID = Depends(verify_access_token),
                     repo: Repository = Depends(get_repo), storage: PrivateStorage = Depends(get_storage)):
    """Return a private PDF only after token verification and owner-scoped lookup."""
    row = _readable_document(repo, owner, document_id)
    if not row:
        raise HTTPException(404, "Document not found")
    if row.get("is_sample"):
        raise HTTPException(403, "The shared sample can only be viewed one cited page at a time")
    try:
        data = storage.download(row["storage_path"])
    except StorageError:
        raise HTTPException(503, "PDF is temporarily unavailable") from None
    if not data.startswith(b"%PDF-"):
        raise HTTPException(503, "PDF is temporarily unavailable")
    return Response(content=data, media_type="application/pdf", headers={
        "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
        "Content-Disposition": "inline; filename=\"document.pdf\"",
    })


@app.get("/api/v1/documents/{document_id}/citations/{passage_id}/page")
def get_sample_citation_page(document_id: UUID, passage_id: UUID,
                             owner: UUID = Depends(verify_access_token),
                             repo: Repository = Depends(get_repo),
                             storage: PrivateStorage = Depends(get_storage)):
    row = _readable_document(repo, owner, document_id)
    if not row or not row.get("is_sample"):
        raise HTTPException(404, "Citation page not found")
    pdf_page = repo.cited_sample_page(row["owner_id"], document_id, passage_id,
                                     row["sha256"], ANSWER_PIPELINE_VERSION)
    if pdf_page is None:
        raise HTTPException(404, "Citation page not found")
    try:
        original = storage.download(row["storage_path"])
        reader = PdfReader(io.BytesIO(original), strict=False)
        if not 1 <= pdf_page <= len(reader.pages):
            raise ValueError("Invalid page number")
        writer = PdfWriter()
        writer.add_page(reader.pages[pdf_page - 1])
        output = io.BytesIO()
        writer.write(output)
    except Exception as exc:
        logger.warning("Could not prepare sample citation page: %s", type(exc).__name__)
        raise HTTPException(503, "Citation page is temporarily unavailable") from None
    return Response(content=output.getvalue(), media_type="application/pdf", headers={
        "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
        "Content-Disposition": "inline; filename=\"cited-page.pdf\"",
    })


@app.delete("/api/v1/documents/{document_id}", status_code=204)
def delete_document(document_id: UUID, owner: UUID = Depends(verify_access_token),
                    repo: Repository = Depends(get_repo), storage: PrivateStorage = Depends(get_storage)):
    # Shared samples are readable but never deletable by another account.
    row = repo.document(owner, document_id)
    if not row:
        raise HTTPException(404, "Document not found")
    try:
        with repo.answer_lock(owner, document_id):
            row = repo.document(owner, document_id)
            if not row:
                raise HTTPException(404, "Document not found")
            # A cache purge must succeed before deleting the irreplaceable PDF bytes.
            repo.delete_saved_answers(owner, document_id)
            try:
                storage.delete(row["storage_path"])
            except StorageError:
                raise HTTPException(503, "Document could not be deleted yet") from None
            repo.delete_document(owner, document_id)
            return Response(status_code=204)
    except AnswerBusy:
        raise HTTPException(503, "Document is busy; please retry") from None


@app.post("/api/v1/documents/{document_id}/chat", response_model=Answer)
def chat(document_id: UUID, payload: ChatRequest, owner: UUID = Depends(verify_access_token),
         repo: Repository = Depends(get_repo), models: HostedModels = Depends(get_models)):
    question = payload.question.strip()
    if len(question) < 8:
        raise HTTPException(400, "Question is too short")
    # Ownership and readiness before any saved-answer lookup or hosted call.
    row = _readable_document(repo, owner, document_id)
    if not row:
        raise HTTPException(404, "Document not found")
    if row["status"] != "ready":
        raise HTTPException(409, "Document is not ready to answer questions")
    try:
        # A shared sample uses one lock so identical guest questions cannot
        # launch duplicate paid generations at the same time.
        lock_owner = row["owner_id"] if row.get("is_sample") else owner
        with repo.answer_lock(lock_owner, document_id):
            # A waiting request must recheck ownership and status after deletion.
            return _chat_locked(document_id, question, owner, repo, models)
    except AnswerBusy:
        raise HTTPException(503, "An answer is still being prepared; please retry") from None


def _chat_locked(document_id: UUID, question: str, owner: UUID,
                 repo: Repository, models: HostedModels) -> Answer:
    row = _readable_document(repo, owner, document_id)
    if not row:
        raise HTTPException(404, "Document not found")
    if row["status"] != "ready":
        raise HTTPException(409, "Document is not ready to answer questions")
    document_sha256 = str(row.get("sha256") or "")
    lookup_started = time.perf_counter()
    cache_owner = row["owner_id"] if row.get("is_sample") else owner
    saved = _find_exact_saved_answer(repo, cache_owner, document_id, question, document_sha256)
    lookup_ms = round((time.perf_counter() - lookup_started) * 1000)
    cfg = settings()
    reserve_args = (owner, document_id, cfg.daily_question_limit,
                    cfg.daily_estimated_usd_limit, cfg.question_reserve_usd,
                    cfg.questions_per_minute_limit)
    if row.get("is_sample") and not saved:
        usage_event = repo.reserve_question(
            *reserve_args, sample_daily_usd_limit=cfg.guest_sample_daily_usd_limit
        )
    else:
        usage_event = repo.reserve_question(*reserve_args)
    if not usage_event:
        raise HTTPException(429, "Daily question or estimated usage limit reached")
    if saved:
        # Exact hit: no Voyage or OpenAI call. Release the $0.05 hold.
        repo.settle_reused_question(owner, usage_event)
        return _answer_from_saved(saved, reused=True, search_ms=lookup_ms)
    embed_tokens = 0
    rerank_tokens = 0
    try:
        start = time.perf_counter()
        vectors, embed_tokens = models.embed([question], "query")
        query_vector = vectors[0]
        passage_owner = row["owner_id"] if row.get("is_sample") else owner
        dense = repo.dense_top(passage_owner, document_id, query_vector, 30)
        lexical = bm25_top(repo.passages(passage_owner, document_id), question, 30)
        pool = fuse(dense, lexical, 20)
        search_ms = round((time.perf_counter() - start) * 1000)
        start = time.perf_counter()
        reranked, rerank_tokens = models.rerank(question, pool)
        top_five = reranked[:5]
        rerank_ms = round((time.perf_counter() - start) * 1000)
        start = time.perf_counter()
        raw, usage = models.answer(question, top_five)
        answer_ms = round((time.perf_counter() - start) * 1000)
    except ProviderUncertainCharge:
        # The provider may have billed the in-flight call. Keep at least the hold.
        known = _estimate_usd(embed_tokens, rerank_tokens, 0, 0)
        repo.settle_question(
            owner, usage_event, embed_tokens + rerank_tokens, 0,
            max(known, cfg.question_reserve_usd),
            provider="uncertain",
        )
        raise HTTPException(503, "Answer service is temporarily unavailable") from None
    except ProviderError:
        known = _estimate_usd(embed_tokens, rerank_tokens, 0, 0)
        repo.settle_question(
            owner, usage_event, embed_tokens + rerank_tokens, 0, known,
            provider="rejected",
        )
        raise HTTPException(503, "Answer service is temporarily unavailable") from None
    sent = {str(p["id"]): p for p in top_five}
    match = raw.get("event_match")
    enough = bool(raw.get("enough_evidence")) and match == "direct_answer"
    unverified_citation = False
    cited = raw.get("supporting_passage_ids") or []
    citations = []
    if enough:
        for passage_id in dict.fromkeys(cited):
            if passage_id not in sent:
                # Never present a model-generated ID or page as evidence.
                enough = False
                unverified_citation = True
                citations = []
                break
            p = sent[passage_id]
            # Full source chunk (at most 450 tokens), so a supporting line at its end is visible.
            citations.append(Citation(passage_id=p["id"], pdf_page=p["pdf_page"], excerpt=p["text"]))
        if not citations:
            enough = False
            unverified_citation = True
    if not enough:
        citations = []
    answer_text = raw["answer"] if enough else "The supplied passages do not confirm the answer to this question."
    evidence_status = "unverified" if unverified_citation else match
    citation_payload = [c.model_dump(mode="json") for c in citations]
    signature = question_signature(question)
    answer_in, answer_out = _usage_from_provider(usage if isinstance(usage, dict) else {})
    estimate = _estimate_usd(embed_tokens, rerank_tokens, answer_in, answer_out)
    repo.settle_question(
        owner, usage_event, embed_tokens + rerank_tokens + answer_in, answer_out, estimate,
        provider="voyage-4-large+rerank-3+gpt-6.1-sol",
    )
    reported = Usage(input_tokens=answer_in, output_tokens=answer_out, estimated_usd=estimate)
    try:
        stored = repo.save_answer(
            cache_owner, document_id, question, signature["canonical"], signature,
            answer_text, enough, evidence_status, citation_payload, document_sha256, ANSWER_PIPELINE_VERSION,
        )
    except DatabaseError as exc:
        # An optional cache write must not discard an answer already paid for.
        logger.warning("Saved-answer cache write failed: %s", type(exc).__name__)
        stored = None
    if stored:
        return _answer_from_saved(
            stored, reused=False, search_ms=search_ms, rerank_ms=rerank_ms, answer_ms=answer_ms,
            usage=reported,
        )
    return Answer(answer=answer_text, enough_evidence=enough, evidence_status=evidence_status,
                  citations=citations, timings_ms=Timings(search=search_ms, rerank=rerank_ms, answer=answer_ms),
                  usage=reported,
                  reused_answer=False)
