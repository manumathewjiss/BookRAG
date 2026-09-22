# Gita RAG Demo UI

Interactive demo for the frozen Bhagavad Gita English→English RAG stack:

**Question → E5 (`query:`) → FAISS Top-5 → Step-14 prompt → Qwen2.5 3B (Ollama)**

This demo does **not** change the FAISS index, chunks, embeddings, or evaluation files.

## What you get

- Ask an English question and see the grounded answer
- Explainable step-by-step view of prefixing, embedding, FAISS retrieval, evidence construction, and LLM generation
- Top-5 retrieved chunks with similarity scores and expandable full text
- Citation status from the existing validator

## Demo modes

1. **Saved-eval replay (instant, recommended for the professor meeting)**  
   Click any sample question chip. The UI shows a real saved E5 Top-5 + Qwen answer from our evaluation runs, plus the explainable pipeline steps.

2. **Live RAG**  
   Type a new question (not in the sample list). The API calls `ask_worker.py` with the RAG venv (`E5 → FAISS → Qwen`).  
   Prefer `~/.venvs/pramod-gita-rag` (outside iCloud/Documents). Override with `GITA_VENV_PYTHON=/path/to/python`.  
   First live call can take ~15–60s while models load.

## Prerequisites

1. For **replay demos**: only the API + UI (Ollama optional)
2. For **live demos**:
   - Ollama running with `qwen2.5:3b`
   - RAG venv at `~/.venvs/pramod-gita-rag` with `faiss`, `sentence-transformers`, `torch`
     (avoid the project `./venv` under Documents if macOS has marked packages as dataless/iCloud)
3. Node.js 18+ for the React UI

## Run (two terminals)

### Terminal 1 — API

From the repo root, using a Python env that already has the Gita RAG packages:

```bash
cd "gita/demo"
# example if you have a working env:
# source /path/to/your/rag-venv/bin/activate

./run_api.sh
```

This starts a stdlib HTTP server (no FastAPI required at runtime) that wraps the frozen E5 + FAISS + Qwen pipeline.

Optional warmup (loads E5 once; first load can take 1–2 minutes):

```bash
curl -X POST http://127.0.0.1:8000/api/warmup
```

### Terminal 2 — UI

```bash
cd "gita/demo/ui"
npm install
npm run dev
```

Open: http://127.0.0.1:5173

The Vite dev server proxies `/api` to `http://127.0.0.1:8000`.

## API endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Artifact + Ollama status, sample questions |
| POST | `/api/warmup` | Preload E5 + FAISS |
| POST | `/api/ask` | Full explainable RAG response |

Example:

```bash
curl -s http://127.0.0.1:8000/api/ask \
  -H 'Content-Type: application/json' \
  -d '{"question":"What does Bhagavad Gita 2.47 say?","top_k":5}' | python -m json.tool | head
```

## Notes for the professor demo

- First question after startup is slower (E5 model load). Click **Warm up E5** first.
- Generation needs Ollama. Retrieval alone still needs the local E5 model.
- This uses the same frozen baseline as Step 14/16: plain E5, not BM25/hybrid.
