"""
Demo API for the frozen Bhagavad Gita English→English RAG stack.

Reuses existing E5 + FAISS + Step-14 Qwen/Ollama settings.
Does not rebuild the index or change retrieval/generation defaults.

Heavy ML imports are deferred until /api/warmup or /api/ask so the
server can start quickly.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

GITA_ROOT = Path(__file__).resolve().parents[2]
if str(GITA_ROOT) not in sys.path:
    sys.path.insert(0, str(GITA_ROOT))

app = FastAPI(
    title="Gita RAG Demo API",
    description="Interactive demo over the frozen E5 + FAISS + Qwen2.5 3B pipeline.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_retriever = None
_load_error: str | None = None
_pipeline = None

TOP_K_DEFAULT = 5
MODEL = "qwen2.5:3b"
OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
TEMPERATURE = 0
NUM_PREDICT = 512
NUM_CTX = 8192
SEED = 0

SAMPLE_QUESTIONS = [
    "What does Bhagavad Gita 2.47 say?",
    "In what way can a person’s own mind be their friend, and in what way can it be their enemy?",
    "What example does the commentary give of a king whose last thought was an animal, and what body did he get next?",
    "How does this Gita distinguish sannyasa, the renounced order, from tyaga, renunciation?",
    "If a person offers Krishna something as simple as a leaf or a little water, but with love, does the Gita say He accepts it?",
]


class AskRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=2000)
    top_k: int = Field(default=TOP_K_DEFAULT, ge=1, le=10)


def load_pipeline():
    """Import gita RAG helpers only when needed."""
    global _pipeline
    if _pipeline is not None:
        return _pipeline
    from rag_generate import E5Retriever, build_context, load_prompt_template
    from rag_generate_step14_qwen import (
        SYSTEM_PROMPT,
        citation_status,
        user_prompt,
        validate_citations,
    )

    _pipeline = {
        "E5Retriever": E5Retriever,
        "build_context": build_context,
        "load_prompt_template": load_prompt_template,
        "SYSTEM_PROMPT": SYSTEM_PROMPT,
        "citation_status": citation_status,
        "user_prompt": user_prompt,
        "validate_citations": validate_citations,
    }
    return _pipeline


def get_retriever():
    global _retriever, _load_error
    if _retriever is not None:
        return _retriever
    if _load_error:
        raise HTTPException(status_code=503, detail=_load_error)
    try:
        pipe = load_pipeline()
        _retriever = pipe["E5Retriever"]()
        return _retriever
    except Exception as exc:  # pragma: no cover
        _load_error = f"Failed to load E5/FAISS: {exc}"
        raise HTTPException(status_code=503, detail=_load_error) from exc


def ollama_reachable() -> bool:
    try:
        req = urllib.request.Request("http://127.0.0.1:11434/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            return resp.status == 200
    except Exception:
        return False


def call_ollama(question: str, context: str, user_prompt_fn, system_prompt: str) -> dict[str, Any]:
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt_fn(question, context)},
        ],
        "stream": False,
        "options": {
            "temperature": TEMPERATURE,
            "num_predict": NUM_PREDICT,
            "num_ctx": NUM_CTX,
            "seed": SEED,
        },
    }
    req = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise HTTPException(
            status_code=503,
            detail="Ollama is not reachable at 127.0.0.1:11434. Start it and ensure qwen2.5:3b is available.",
        ) from exc

    answer = ((data.get("message") or {}).get("content") or "").strip()
    return {
        "answer": answer,
        "prompt_eval_count": data.get("prompt_eval_count"),
        "eval_count": data.get("eval_count"),
        "done_reason": data.get("done_reason"),
    }


def preview(text: str, n: int = 220) -> str:
    t = " ".join((text or "").split())
    return t if len(t) <= n else t[: n - 1] + "…"


def hit_payload(hit: dict) -> dict:
    body = hit["text"]
    if "\n\n" in body:
        body = body.split("\n\n", 1)[1]
    return {
        "rank": hit["rank"],
        "score": hit.get("score"),
        "chunk_id": hit["chunk_id"],
        "source_record_id": hit["source_record_id"],
        "chapter": hit["chapter"],
        "verse_start": hit["verse_start"],
        "verse_end": hit["verse_end"],
        "section": hit["section"],
        "part": hit.get("part"),
        "n_parts": hit.get("n_parts"),
        "page_start": hit.get("page_start"),
        "page_end": hit.get("page_end"),
        "text": hit["text"],
        "body_preview": preview(body, 320),
        "similarity_note": (
            "FAISS IndexFlatIP score on L2-normalized E5 vectors "
            "(≈ cosine similarity; closer to 1.0 = more similar)."
        ),
    }


@app.get("/api/health")
def health() -> dict:
    index_ok = (GITA_ROOT / "gita_e5.faiss").exists()
    meta_ok = (GITA_ROOT / "gita_e5_metadata.json").exists()
    prompt_ok = (GITA_ROOT / "gita_rag_prompt.txt").exists()
    return {
        "status": "ok",
        "pipeline": "plain_e5 + faiss IndexFlatIP + qwen2.5:3b (Ollama)",
        "e5_model": "intfloat/multilingual-e5-large",
        "embedding_dim": 1024,
        "n_chunks": 1443,
        "top_k_default": TOP_K_DEFAULT,
        "generator": MODEL,
        "num_ctx": NUM_CTX,
        "temperature": TEMPERATURE,
        "artifacts": {
            "faiss_index": index_ok,
            "metadata": meta_ok,
            "prompt": prompt_ok,
        },
        "ollama_reachable": ollama_reachable(),
        "retriever_loaded": _retriever is not None,
        "sample_questions": SAMPLE_QUESTIONS,
    }


@app.post("/api/warmup")
def warmup() -> dict:
    t0 = time.perf_counter()
    get_retriever()
    return {
        "status": "ready",
        "load_seconds": round(time.perf_counter() - t0, 2),
        "ollama_reachable": ollama_reachable(),
    }


@app.post("/api/ask")
def ask(req: AskRequest) -> dict:
    question = req.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question is empty.")

    pipe = load_pipeline()
    build_context = pipe["build_context"]
    load_prompt_template = pipe["load_prompt_template"]
    system_prompt = pipe["SYSTEM_PROMPT"]
    citation_status = pipe["citation_status"]
    user_prompt = pipe["user_prompt"]
    validate_citations = pipe["validate_citations"]

    timings: dict[str, float] = {}
    steps: list[dict] = []

    steps.append(
        {
            "id": "receive",
            "title": "Receive English question",
            "simple": "The user typed a question in English about the Bhagavad Gita.",
            "detail": question,
            "status": "done",
        }
    )

    prefixed = f"query: {question}"
    steps.append(
        {
            "id": "prefix",
            "title": 'Add E5 "query:" prefix',
            "simple": "E5 expects questions to start with query: so the model knows this is a search question, not a book passage.",
            "detail": prefixed,
            "status": "done",
        }
    )

    retriever = get_retriever()
    t0 = time.perf_counter()
    hits = retriever.retrieve(question, top_k=req.top_k)
    timings["retrieve_ms"] = round((time.perf_counter() - t0) * 1000, 1)

    steps.append(
        {
            "id": "embed",
            "title": "Embed question with multilingual-e5-large",
            "simple": "E5 turns the question into 1024 numbers (a vector) that represent meaning.",
            "detail": {
                "model": "intfloat/multilingual-e5-large",
                "vector_dim": 1024,
                "normalized": True,
                "device_note": "SentenceTransformer encode uses CPU in this stack.",
            },
            "status": "done",
            "elapsed_ms": timings["retrieve_ms"],
        }
    )

    steps.append(
        {
            "id": "faiss",
            "title": "Search FAISS IndexFlatIP",
            "simple": "FAISS finds the book chunks whose vectors are closest to the question vector (Top-K nearest neighbors).",
            "detail": {
                "index": "IndexFlatIP",
                "n_vectors": 1443,
                "top_k": req.top_k,
                "similarity": "inner product ≈ cosine similarity on normalized vectors",
                "top_chunk_ids": [h["chunk_id"] for h in hits],
                "top_scores": [round(float(h["score"]), 4) for h in hits],
            },
            "status": "done",
        }
    )

    t1 = time.perf_counter()
    context, hits_ctx = build_context(hits)
    timings["context_ms"] = round((time.perf_counter() - t1) * 1000, 1)
    n_blocks = context.count("[EVIDENCE ")

    steps.append(
        {
            "id": "context",
            "title": "Build text evidence for the LLM",
            "simple": "The LLM does not see FAISS vectors. It receives the original English Translation/Purport text, labeled as evidence.",
            "detail": {
                "evidence_blocks": n_blocks,
                "all_top_k_supplied": n_blocks == len(hits),
                "context_chars": len(context),
                "context_preview": preview(context, 500),
            },
            "status": "done",
            "elapsed_ms": timings["context_ms"],
        }
    )

    prompt_template = load_prompt_template()
    full_user = user_prompt(question, context)

    steps.append(
        {
            "id": "prompt",
            "title": "Apply grounded generation prompt (Step 14)",
            "simple": "Instructions tell Qwen to answer only from the retrieved evidence and to cite verse/source.",
            "detail": {
                "prompt_file": "gita_rag_prompt.txt",
                "system_chars": len(system_prompt),
                "user_chars": len(full_user),
                "template_preview": preview(prompt_template, 360),
            },
            "status": "done",
        }
    )

    t2 = time.perf_counter()
    gen = call_ollama(question, context, user_prompt, system_prompt)
    timings["generate_ms"] = round((time.perf_counter() - t2) * 1000, 1)
    timings["total_ms"] = round(
        timings["retrieve_ms"] + timings["context_ms"] + timings["generate_ms"], 1
    )

    cites = validate_citations(gen["answer"], hits)
    cite_label = citation_status(gen["answer"], hits)

    steps.append(
        {
            "id": "llm",
            "title": "Generate answer with Qwen2.5 3B (Ollama)",
            "simple": "Ollama is the local runtime. Qwen2.5 3B is the language model that writes the English answer from the evidence.",
            "detail": {
                "provider": "ollama",
                "model": MODEL,
                "temperature": TEMPERATURE,
                "num_ctx": NUM_CTX,
                "num_predict": NUM_PREDICT,
                "seed": SEED,
                "prompt_eval_count": gen.get("prompt_eval_count"),
                "eval_count": gen.get("eval_count"),
                "done_reason": gen.get("done_reason"),
            },
            "status": "done",
            "elapsed_ms": timings["generate_ms"],
        }
    )

    steps.append(
        {
            "id": "answer",
            "title": "Return grounded English answer",
            "simple": "The UI shows the answer plus the retrieved evidence so you can see what supported it.",
            "detail": {
                "citation_status": cite_label,
                "cited_source_ids": cites["cited_source_ids"],
                "unsupported_citations": cites["unsupported_citations"],
            },
            "status": "done",
        }
    )

    return {
        "question": question,
        "answer": gen["answer"],
        "pipeline_steps": steps,
        "retrieval": {
            "retriever": "plain_e5",
            "e5_model": "intfloat/multilingual-e5-large",
            "query_prefix": "query: ",
            "faiss_index": "IndexFlatIP",
            "n_chunks": 1443,
            "top_k": req.top_k,
            "hits": [hit_payload(h) for h in hits_ctx],
        },
        "generation": {
            "model": MODEL,
            "provider": "ollama",
            "temperature": TEMPERATURE,
            "num_ctx": NUM_CTX,
            "num_predict": NUM_PREDICT,
            "seed": SEED,
            "prompt_eval_count": gen.get("prompt_eval_count"),
            "eval_count": gen.get("eval_count"),
            "done_reason": gen.get("done_reason"),
            "context_sent_to_llm": context,
            "system_prompt": system_prompt,
        },
        "citations": {
            **cites,
            "citation_status": cite_label,
        },
        "timings_ms": timings,
        "architecture_note": (
            "This is the frozen working baseline: multilingual-e5-large → FAISS → Top-5 "
            "→ Step-14 prompt → qwen2.5:3b. BM25/hybrid/section-aware are not used here."
        ),
    }


@app.get("/")
def root() -> dict:
    return {
        "message": "Gita RAG Demo API",
        "docs": "/docs",
        "health": "/api/health",
        "ask": "POST /api/ask",
    }
