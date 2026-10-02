# books/ — generic AI book-learning platform (Stage 1)

This directory is **new research**, isolated from:

- `gita/` — frozen Bhagavad Gita RAG baseline
- `src/` and related Itihasa/Sanskriti code — senior’s legacy, reference-only

## Stage 1 only

Research question: can an arbitrary **digital-text** PDF become clean, metadata-preserving, **E5-safe** chunks?

```
Digital PDF
  → LangChain PyPDFLoader
  → List[Document] + page/source metadata
  → light cleaning
  → RecursiveCharacterTextSplitter (E5 content-token target)
  → validate every chunk: tokenizer("passage: " + text, add_special_tokens=True) ≤ 512
  → validation JSON
  → STOP
```

Not in Stage 1: embeddings, FAISS, PostgreSQL/pgvector, Qwen/Ollama, OCR, question generation, scoring, UI.

## Environment

Use the isolated venv (not the Gita venv, not `./venv`):

```bash
source ~/.venvs/pramod-books-rag/bin/activate
```

## Sample PDF

Place **one digital-text PDF** (selectable text, not a scan) at:

```
books/sample_pdfs/<your-file>.pdf
```

Do **not** use the Bhagavad Gita PDF.

## Run

```bash
cd "/Users/manumathewjiss/Documents/Pramod Gupta Project"
source ~/.venvs/pramod-books-rag/bin/activate
python books/ingest_stage1.py --pdf books/sample_pdfs/<your-file>.pdf
```

The report is written to `books/outputs/<book_id>_stage1_validation.json`.
The exact validated chunks are written to `books/outputs/<book_id>_stage1_chunks.json` (Stage 2 input).

## Stage 2 (embeddings + pgvector storage)

After Stage 1 chunks exist:

```bash
source ~/.venvs/pramod-books-rag/bin/activate
python books/embed_stage2.py --chunks books/outputs/thinkpython_stage1_chunks.json
```

Requires PostgreSQL 16 with the `vector` extension, database `books_rag`, and
`BOOKS_DATABASE_URL` if not using the default local URL.

## Token rules

- Target: ~400–450 **content** tokens, ~40–50 content-token overlap
- Hard limit: E5 input (`"passage: "` + chunk + special tokens) **≤ 512**
- Over-limit first-pass chunks are **split further**, never truncated or dropped

## Stage 3 (query retrieval + metrics)

Stage 3 ends at **retrieval**. Qwen / Ollama / answer generation are **not** included.

```
question
  → "query: " + question
  → intfloat/multilingual-e5-large
  → L2-normalized 1024-D query embedding
  → exact pgvector search (embedding <#> query, filter book_id)
  → Top-K stored chunks (original text + page + chunk_index + similarity)
  → retrieval metrics (Hit/Recall@1/5/10, MRR@10)
```

Interactive retrieval:

```bash
source ~/.venvs/pramod-books-rag/bin/activate
python books/retrieve_stage3.py \
  --book-id thinkpython \
  --question "What does the modulus operator return?" \
  --top-k 5
```

Frozen evaluation (gold labels from Stage 1 chunks, chosen before search):

```bash
python books/evaluate_retrieval_stage3.py
```

Outputs:

- `books/outputs/thinkpython_retrieval_eval_frozen.json`
- `books/outputs/thinkpython_stage3_retrieval_results.json`
- `books/outputs/thinkpython_stage3_retrieval_summary.json`

Passage embeddings from Stage 2 are not recomputed.
