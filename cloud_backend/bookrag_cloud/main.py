from __future__ import annotations

import hashlib
import time
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from .config import settings
from .providers import HostedModels, ProviderError
from .repository import Repository, UsageLimitReached
from .retrieval import bm25_top, fuse
from .schemas import Answer, ChatRequest, Citation, Document, Timings, Usage
from .security import verify_access_token
from .storage import PrivateStorage, StorageError


def get_repo() -> Repository:
    return Repository(settings().database_url)


def get_storage() -> PrivateStorage:
    return PrivateStorage(settings())


def get_models() -> HostedModels:
    return HostedModels(settings())


app = FastAPI(title="BookRAG Cloud API", version="1.0.0", docs_url="/api/v1/docs", openapi_url="/api/v1/openapi.json")
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
    return {"documents": [Document.model_validate(row) for row in repo.list_documents(owner)]}


@app.get("/api/v1/documents/{document_id}")
def get_document(document_id: UUID, owner: UUID = Depends(verify_access_token), repo: Repository = Depends(get_repo)):
    row = repo.document(owner, document_id)
    if not row:
        raise HTTPException(404, "Document not found")
    return {"document": Document.model_validate(row)}


@app.delete("/api/v1/documents/{document_id}", status_code=204)
def delete_document(document_id: UUID, owner: UUID = Depends(verify_access_token),
                    repo: Repository = Depends(get_repo), storage: PrivateStorage = Depends(get_storage)):
    row = repo.document(owner, document_id)
    if not row:
        raise HTTPException(404, "Document not found")
    try:
        storage.delete(row["storage_path"])
    except StorageError:
        raise HTTPException(503, "Document could not be deleted yet") from None
    repo.delete_document(owner, document_id)
    return Response(status_code=204)


@app.post("/api/v1/documents/{document_id}/chat", response_model=Answer)
def chat(document_id: UUID, payload: ChatRequest, owner: UUID = Depends(verify_access_token),
         repo: Repository = Depends(get_repo), models: HostedModels = Depends(get_models)):
    question = payload.question.strip()
    if len(question) < 8:
        raise HTTPException(400, "Question is too short")
    row = repo.document(owner, document_id)
    if not row:
        raise HTTPException(404, "Document not found")
    if row["status"] != "ready":
        raise HTTPException(409, "Document is not ready to answer questions")
    cfg = settings()
    usage_event = repo.reserve_question(owner, document_id, cfg.daily_question_limit,
                                        cfg.daily_estimated_usd_limit, cfg.question_reserve_usd,
                                        cfg.questions_per_minute_limit)
    if not usage_event:
        raise HTTPException(429, "Daily question or estimated usage limit reached")
    try:
        start = time.perf_counter()
        vector, embed_tokens = models.embed([question], "query")
        dense = repo.dense_top(owner, document_id, vector[0], 30)
        lexical = bm25_top(repo.passages(owner, document_id), question, 30)
        pool = fuse(dense, lexical, 20)
        search_ms = round((time.perf_counter() - start) * 1000)
        start = time.perf_counter()
        reranked, rerank_tokens = models.rerank(question, pool)
        top_five = reranked[:5]
        rerank_ms = round((time.perf_counter() - start) * 1000)
        start = time.perf_counter()
        raw, usage = models.answer(question, top_five)
        answer_ms = round((time.perf_counter() - start) * 1000)
    except ProviderError:
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
    in_tokens = int(usage.get("input_tokens", 0))
    out_tokens = int(usage.get("output_tokens", 0))
    estimate = round((embed_tokens * .12 + rerank_tokens * .05 + in_tokens * 2 + out_tokens * 10) / 1_000_000, 6)
    repo.settle_question(owner, usage_event, embed_tokens + rerank_tokens + in_tokens, out_tokens, estimate)
    return Answer(answer=raw["answer"] if enough else "The supplied passages do not confirm the answer to this question.",
                  enough_evidence=enough, evidence_status="unverified" if unverified_citation else match,
                  citations=citations, timings_ms=Timings(search=search_ms, rerank=rerank_ms, answer=answer_ms),
                  usage=Usage(input_tokens=in_tokens, output_tokens=out_tokens, estimated_usd=estimate))
