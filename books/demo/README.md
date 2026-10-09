# Local BookRAG demo

Not production. Localhost only. Hybrid BGE-M3 top-20 → local Qwen top-5 → Sol.

**Presentation books (picker order):** Bhagavad-gītā As It Is, Arthashastra (Temple Library excerpt), Think Python. Frankenstein and Pride and Prejudice remain available so earlier demos stay recoverable.

Citations are labeled **PDF page** (Stage 1 metadata). A short excerpt is chosen around the supporting sentence when possible (boilerplate stripped for display only). If that window cannot be found reliably, the UI shows the full passage for inspection instead of pretending the start of the chunk is proof.

Optional local guards (env): `DEMO_MAX_CALLS`, `DEMO_MAX_USD`, `DEMO_MAX_QUESTION_CHARS`, `DEMO_MAX_REQUEST_BYTES`. These are **session estimate limits**, not the OpenAI account balance.

Both professor PDFs were already chunked and indexed in Postgres; those indexes were reused (not re-ingested).

## Start

```bash
source ~/.venvs/pramod-books-rag/bin/activate
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
cd "/Users/manumathewjiss/Documents/Pramod Gupta Project/books"
python demo/app.py
```

Startup loads local models and book indexes **before** questions are accepted (printed in the terminal; not part of question wait). Then open http://127.0.0.1:5055

The professor desk starts **empty**. Click **+** to attach a digital-text PDF; a fixed pipeline runs (extract → chunk → store → BGE-M3 dense → hybrid sparse → ready). Then ask. Preloaded books stay available at http://127.0.0.1:5055/classic. This is ordinary orchestration in code, not a LangGraph agent.

Needs gitignored `books/.env`, PostgreSQL `books_rag`, and existing embeddings. Do not put the key in chat, Git, or result files.

## Short presentation order

1. **Bhagavad-gītā As It Is** — living-entity birth/death (expect PDF page **26**); four kinds of pious men (PDF page **468**); then “Arjuna’s email address” (honest refusal).
2. **Arthashastra** — wages (PDF page **2**); local vs imported profit margins (PDF page **3**); then India’s GDP last year (honest refusal). Remind the audience this PDF is an **8-page excerpt**, not the full classical work.
3. **Think Python** — high-level / portable (PDF page **23**); string `+` / `*` (PDF page **38**); TensorFlow/PyTorch install (refusal / related only).

Exact wording and expected answers: `books/outputs/professor_demo_presentation_plan.json`.

## Risks

- Arthashastra coverage is thin (10 chunks / 8 pages).
- Wording-sensitive literary questions can still miss the exact line (unchanged limitation).
- First question after startup is fine if you wait for the “models loaded” line; total wait per question is still mostly Qwen + Sol (~10–20s here).
