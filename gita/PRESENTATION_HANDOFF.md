# Bhagavad Gita English→English RAG — Presentation Handoff Report

**Purpose:** Give ChatGPT everything needed to build a short professor PowerPoint.  
**Rule:** Numbers and claims below come from saved project files / validated scripts. Nothing here invents results.  
**Completed vs proposed:** Completed work is labeled clearly. Proposed larger-model / cloud-GPU work has **not** been run.

**Source PDF:** `data/Bhagavad-gita_As_It_Is.pdf` (Prabhupada / BBT “Bhagavad-gita As It Is”)  
**Working code & artifacts:** `gita/`

---

## 0. Story the slides should tell (simple English)

```
Bhagavad Gita PDF
  → Extract and structure the text
  → Create meaningful English chunks
  → E5 embeddings (meaning as numbers)
  → FAISS retrieval (find nearest chunks)
  → Evaluate retrieval
  → Compare retrieval approaches (BM25, hybrid)
  → Add an LLM for answers
  → FLAN-T5-small experiment (failed)
  → Qwen2.5 3B + Ollama experiment (works)
  → Fresh end-to-end evaluation (40 questions)
  → Current limitations
  → Proposed larger-model / cloud-GPU experiment (NOT done yet)
```

**One-sentence system description:**  
Ask an English question about the Bhagavad Gita; the system finds the most relevant English passages from the book, then a local language model writes an English answer using only those passages.

---

## 1. Original project goal

### What problem were we asked to solve?
Build an **English-to-English question-answering system** over the Bhagavad Gita book (PDF), so a user can ask in English and get an answer grounded in this edition’s English translation and purport (commentary)—not a free-floating LLM guess.

### What was the Bhagavad Gita PDF?
- File: `data/Bhagavad-gita_As_It_Is.pdf`
- Edition style: BBT “Bhagavad-gita As It Is” with **TEXT / TEXTS**, **SYNONYMS**, **TRANSLATION**, **PURPORT**
- Step-1 inspection found ~**1051** PDF pages (digital text; not a scan-only book)
- Verse content starts around PDF page **43**; structured records span pages **43–1029**
- Pages **2–3** are image-only (no extractable text)
- Front matter (intro, etc.) and publisher back matter were **not** turned into verse records

### What should the final system do?
1. Accept an English question  
2. Retrieve the most relevant English chunks (translation and/or purport)  
3. Generate a clear English answer **supported by that retrieved text**  
4. Cite the verse/source used  

### Why RAG instead of asking an LLM directly?
**RAG = Retrieval-Augmented Generation.**

Simple analogy:
- An LLM alone is like a student answering from memory (can invent verses).
- RAG is like a student who must **open the book**, find the page, then answer **from that page**.

We chose RAG so answers stay tied to **this PDF’s** translation and purport.

---

## 2. PDF inspection and extraction

**Script:** `gita/extract_chapter.py`  
**Outputs:** `gita/gita_structured.json`, `gita/gita_validation.json`  
**Library:** `pypdf` (`PdfReader`) — extract text per page (no OCR).

### Structure of the PDF (how the book is laid out)
Each verse block typically has:
1. **TEXT n** or **TEXTS n–m** heading  
2. Sanskrit (Devanagari) + transliteration (often garbled by PDF text extraction)  
3. **SYNONYMS** (word glossary)  
4. **TRANSLATION** (English verse meaning)  
5. **PURPORT** (English commentary) — sometimes missing  

Chapters marked with banners like `- CHAPTER N -` (18 chapters).

### Exact corpus counts (from `gita_validation.json`)

| Item | Count |
|---|---:|
| Chapters | 18 |
| Traditional verse numbers covered | **700** |
| Structured records (TEXT/TEXTS blocks) | **657** |
| Single TEXT records | 627 |
| Grouped TEXTS records | 30 |
| With purport | 625 |
| Without purport | 32 |
| Empty translations | 0 |
| Empty synonyms | 0 |
| Chapters with validation issues | 0 |

### Why 700 verses → 657 records?
The book sometimes prints **several verse numbers in one block** (`TEXTS 16–18`).  
Those stay **one JSON record** with `verse_start` / `verse_end`, not separate fake rows.

- 627 single-verse TEXT records + 30 grouped TEXTS records = **657**  
- Expanding ranges still covers all **700** traditional verse numbers  
- Extra verse slots absorbed into groups: **43** (= 700 − 657)

### Grouped TEXT/TEXTS behavior
- `TEXT 1` → one verse  
- `TEXTS 16–18` → one record, identity like `1.16-18`  
- Identity preserved through chunking and retrieval  

### Sanskrit / transliteration issues
PDF extraction of Devanagari is **garbled** (punctuation-heavy blobs). Transliteration uses special Latin characters.  
**English RAG decision:** search and answer on **Translation + Purport**, not Sanskrit/transliteration as primary text. Synonyms are kept on the record but **not** embedded.

### Pages excluded from the verse corpus
- Front matter before Chapter 1 verse content  
- Image-only pages 2–3  
- Publisher catalog / back matter after Chapter 18 (cut at publisher string)  
- Repeating copyright footer lines stripped during extraction  

### Important validation checks
Per chapter: expected traditional verse counts, no missing/duplicate verses, no empty translation/synonyms, `has_purport` flag matches purport text, page_start ≤ page_end.

### Important extraction snippet (`extract_chapter.py`)

```python
# TEXT  1   or   TEXTS  16–18
TEXT_HEADING_RE = re.compile(
    r"^(TEXTS?)\s+(\d+)(?:\s*[–—-]\s*(\d+))?\s*$",
    re.MULTILINE,
)

def extract_pages(pdf_path: Path) -> list[tuple[int, str]]:
    reader = PdfReader(str(pdf_path))
    pages = []
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        text = COPYRIGHT_RE.sub("", text)
        pages.append((i + 1, text))
    return pages
```

**What it does:** Reads every PDF page as text, strips the repeating copyright line, and later splits on TEXT/TEXTS + SYNONYMS/TRANSLATION/PURPORT headings.

### Example structured JSON record (shortened)

```json
{
  "chapter": 1,
  "verse_start": 1,
  "verse_end": 1,
  "text_label": "TEXT 1",
  "synonyms": "dhåtaräñöraù uväca—King Dhåtaräñöra said; ...",
  "translation": "Dhåtaräñöra said: O Saïjaya, after my sons and the sons of Päëòu assembled...",
  "purport": "Bhagavad-gétä is the widely read theistic science...",
  "has_purport": true,
  "page_start": 43,
  "page_end": 45
}
```

Grouped example: Chapter 1 `TEXTS 16–18` → `verse_start=16`, `verse_end=18`, pages 59–61.

---

## 3. Chunking

**Script:** `gita/chunker.py`  
**Outputs:** `gita/gita_chunks.json`, `gita/gita_chunk_validation.json`, `gita/chunk_samples.json`

### Why not embed the whole PDF or whole long records?
E5 only accepts **512 tokens** (~350–400 English words). A purport can be **thousands of words**. Embedding an unsplit long purport would **truncate** and lose searchable content.

### Design (actual)
| Section | Rule |
|---|---|
| Translation | Always **one intact** chunk (never split; max ~131 words in this book) |
| Purport | Keep whole if ≤ ~350 words; else split to ~350 words with **40-word overlap**; hard max body ~**420** words |
| Synonyms | Preserved on source record; **not** used as main embedding text |
| Grouped verses | Keep one source identity (e.g. `1.16-18`) |
| No purport | Translation chunk only |

### Exact final chunk counts (`gita_chunk_validation.json`)
| Item | Count |
|---|---:|
| Source records | 657 |
| **Total chunks** | **1443** |
| Translation chunks | 657 |
| Purport chunks | 786 |
| Purports unsplit | 510 |
| Purports split | 115 |
| Max purport parts | 8 |
| Empty texts | 0 |
| Duplicate chunk IDs | 0 |
| Overlap pairs fail | 0 |
| Purport preservation fail | 0 |
| Traditional verses in chunks | 700 |

### Chunk examples

**Translation (`2.47#translation`):**
```
Bhagavad-gita 2.47 — Translation

You have a right to perform your prescribed duty, but you are not entitled to the fruits of action. Never consider yourself the cause of the results of your activities, and never be attached to not doing your duty.
```

**Unsplit purport (`2.47#purport.1`):** starts with `Bhagavad-gita 2.47 — Purport` then commentary (~260 words).

**Split purport (`9.2`):** 6 parts — `9.2#purport.1` … `9.2#purport.6`, headings like `Purport (part 1 of 6)`.

### Important chunking snippet (`chunker.py`)

```python
TARGET_PURPORT_WORDS = 350
MAX_PURPORT_WORDS = 420
OVERLAP_WORDS = 40

trans_text = f"{cite} — Translation\n\n{record['translation'].strip()}"
chunks.append({"chunk_id": f"{rid}#translation", "section": "translation", "text": trans_text, ...})

parts = split_purport(record["purport"])
for i, part_text in enumerate(parts, start=1):
    chunks.append({"chunk_id": f"{rid}#purport.{i}", "section": "purport",
                   "text": f"{heading}\n\n{part_text.strip()}", ...})
```

**What it does:** One translation chunk per verse record; long commentaries are split with overlap so meaning is not lost at cut points.

---

## 4. E5 embeddings

**Script:** `gita/build_e5_index.py`  
**Model:** `intfloat/multilingual-e5-large`  
**Dim:** **1024** numbers per chunk  
**Artifacts:** `gita_e5.faiss`, `gita_e5_metadata.json`, `gita_e5_truncation_report.json`

### Beginner explanation
E5 is a model that turns text into a list of **1024 numbers** (a vector) that represent **meaning**.  
Similar meanings → similar vectors.

```
Text  →  E5  →  1024 numbers (vector)
```

### Prefixes (required by E5)
- Documents: `"passage: " + text`  
- Questions: `"query: " + question`  

### Normalization
Vectors are **L2-normalized**. With normalized vectors, FAISS **inner product ≈ cosine similarity**.

### Token / context limit
- `max_seq_length = 512`  
- Truncation report: **221 / 1443** chunks exceed 512 tokens (would be truncated by E5). Chunker was **not** changed in that step; report is documented in `gita_e5_truncation_report.json`.  
- Median tokens ~136; max before truncation observed **866**.

### Important embedding snippet (`build_e5_index.py`)

```python
MODEL_NAME = "intfloat/multilingual-e5-large"

def passage_input(text: str) -> str:
    return "passage: " + text

embeddings = model.encode(
    inputs,
    batch_size=16,
    convert_to_numpy=True,
    normalize_embeddings=True,
    device="cpu",
)
```

**What it does:** Prefixes each chunk with `passage:`, embeds with multilingual-e5-large, and unit-normalizes the vectors.

---

## 5. FAISS

**Beginner explanation:**  
- **E5** = turns meaning into vectors  
- **FAISS** = a fast library that searches those vectors for the **nearest neighbors**

### Actual index
| Setting | Value |
|---|---|
| Index type | **IndexFlatIP** (exact inner product; no approximate ANN) |
| Similarity | Inner product on L2-normalized vectors ≈ cosine |
| Vectors indexed | **1443** |
| Dimension | **1024** |
| Eval Top-K | **10** (retrieval eval) |
| Generation Top-K | **5** (answer generation) |

### Indexing snippet

```python
index = faiss.IndexFlatIP(dim)
index.add(embeddings)
faiss.write_index(index, str(args.index))
```

### Search snippet (`evaluate_e5.py` / `rag_generate.py`)

```python
def query_input(question: str) -> str:
    return "query: " + question

q_emb = model.encode(query_texts, normalize_embeddings=True, ...)
scores, rows = index.search(q_emb, top_k)
```

**What it does:** Encodes the question with `query:`, then FAISS returns the Top-K most similar chunk rows.

---

## 6. Complete retrieval pipeline (flowchart)

```
English Question
      ↓
Add "query: " prefix
      ↓
E5 (multilingual-e5-large)
      ↓
Query Vector (1024 numbers, normalized)
      ↓
FAISS IndexFlatIP
      ↓
Top-5 (generation) / Top-10 (eval) most similar chunks
      ↓
Retrieve original English TEXT + metadata
(chapter, verse, Translation vs Purport, chunk_id)
```

**Visual file:** `gita/presentation_assets/pipeline_flowchart.png`

---

## 7. Retrieval evaluation

### Metrics (one sentence each)
- **Recall@1:** Was a correct gold source/chunk the single top hit?  
- **Recall@5:** Was a correct gold somewhere in the top 5?  
- **Recall@10:** Was a correct gold somewhere in the top 10?  
- **MRR:** How high (on average) was the first correct hit? (1/rank; higher is better)

### SOURCE-level vs EXACT-CHUNK
- **SOURCE-level:** Correct if any gold **verse/source ID** appears (e.g. `2.47`), even if wrong section (translation vs purport).  
- **EXACT-CHUNK:** Correct only if the gold **chunk_id** appears (e.g. `2.47#translation`).

Scoring rule (frozen): any valid gold counts as the first hit; not all golds need to appear; missing from top-10 → 0 for that question.

### A) Initial frozen 30-question evaluation
**Files:** `gita_eval_frozen.json`, `gita_e5_eval_summary.json`  
**Distribution:** citation 5, factual 7, conceptual 7, purport 6, terminology 5; easy 6 / medium 17 / hard 7  

**Plain E5 (source-level):**
| Metric | Value |
|---|---:|
| Recall@1 | **0.700** (70%) |
| Recall@5 | **0.833** (83.3%) |
| Recall@10 | **0.967** (96.7%) |
| MRR@10 | **0.773** |

**Plain E5 (exact-chunk):**
| Metric | Value |
|---|---:|
| Recall@1 | 0.600 |
| Recall@5 | 0.767 |
| Recall@10 | 0.800 |
| MRR@10 | 0.676 |

### B) Fresh held-out 40-question retrieval evaluation
**Files:** `gita_holdout_frozen.json`, `gita_holdout_eval_summary.json`, `gita_holdout_validation.json`  
**Distribution:** 8 each of citation / factual / conceptual / purport / terminology; easy 10 / medium 18 / hard 12; **all 18 chapters** represented; frozen before retrieval; no tuning after holdout.

**Plain E5 (source-level) — strongest fresh retrieval numbers:**
| Metric | Value |
|---|---:|
| Recall@1 | **0.900** (90%) |
| Recall@5 | **1.000** (100%) |
| Recall@10 | **1.000** (100%) |
| MRR@10 | **0.946** |

**Plain E5 (exact-chunk):**
| Metric | Value |
|---|---:|
| Recall@1 | **0.825** (82.5%) |
| Recall@5 | **0.925** (92.5%) |
| Recall@10 | 0.975 |
| MRR@10 | 0.874 |

---

## 8. BM25 experiment

**Why tested:** Keyword matching baseline vs semantic E5.  
**Simple:** E5 ≈ meaning; BM25 ≈ word overlap.  
**Files:** `evaluate_bm25.py`, `gita_bm25_eval_summary.json`  
**Method:** BM25Okapi over the same 1443 chunk texts; dotted verse tokens preserved (e.g. `11.32`).

### Exact BM25 results (same frozen 30 questions)

| Level | R@1 | R@5 | R@10 | MRR@10 |
|---|---:|---:|---:|---:|
| Source BM25 | 0.467 | 0.633 | 0.833 | 0.538 |
| Source E5 | **0.700** | **0.833** | **0.967** | **0.773** |
| Chunk BM25 | 0.333 | 0.567 | 0.700 | 0.427 |
| Chunk E5 | **0.600** | **0.767** | **0.800** | **0.676** |

**Did BM25 beat E5?** No overall. E5 better on 8 questions; BM25 better on 3; BM25-only hit 1; E5-only 5; ties 13.  
**Lesson:** Semantic retrieval dominates conceptual questions; BM25 can help some citation/keyword cases.

---

## 9. Hybrid / RRF and secondary experiments

### Hybrid RRF
Combine E5 Top-50 + BM25 Top-50 with Reciprocal Rank Fusion (`rrf_k=60`), fuse by `chunk_id`.

**30-question source-level:**
| System | R@1 | R@5 | R@10 | MRR@10 |
|---|---:|---:|---:|---:|
| E5 | **0.700** | 0.833 | 0.967 | **0.773** |
| BM25 | 0.467 | 0.633 | 0.833 | 0.538 |
| Hybrid RRF | 0.667 | **0.867** | **1.000** | 0.754 |

**Held-out 40 source-level:**
| System | R@1 | R@5 | R@10 | MRR@10 |
|---|---:|---:|---:|---:|
| E5 | **0.900** | **1.000** | **1.000** | **0.946** |
| BM25 | 0.550 | 0.775 | 0.825 | 0.644 |
| Hybrid RRF | 0.725 | 0.925 | 0.950 | 0.802 |

**Why we did NOT replace plain E5 with hybrid:** Hybrid helped some citation recoveries on the 30-q set (e.g. R@10 → 1.0) but **did not beat E5** on the held-out 40 for R@1 / R@5 / MRR. Plain E5 stayed the best overall retriever.

### Citation-gated (secondary)
If question contains `\b\d{1,2}\.\d{1,3}\b`, use Hybrid RRF; else E5.  
- On 30-q (exploratory / same-set motivated): source R@1 **0.733**, R@5 0.867, R@10 1.0, MRR 0.798  
- On held-out 40: **identical to E5** (0.90 / 1.0 / 1.0 / 0.946) — gated routing did not change overall holdout metrics vs plain E5

### Section-aware (secondary)
Same-source preference for Translation vs Purport after E5 Top-50.  
- Dev 30: source metrics essentially unchanged; exact-chunk R@1 0.60 → **0.667**  
- Former holdout 40 (as development): exact-chunk R@1 0.825 → **0.850**, R@5 0.925 → **0.975**  
- Not adopted as the final generation retriever (kept plain E5).

---

## 10. Final retrieval decision

**Kept architecture:**  
`multilingual-e5-large` + `passage:`/`query:` + L2 normalize + **FAISS IndexFlatIP** + **Top-5** for generation (Top-10 for retrieval eval).

**Not used in the final answer pipeline:** BM25-only, RRF hybrid, citation gating, section-aware rerank.

**Why:** Strongest held-out retrieval; simplest; generation experiments froze this stack.

**Prominently report (held-out 40, E5):**
- Source Recall@1 = **90%**  
- Source Recall@5 = **100%**  
- Exact-chunk Recall@1 = **82.5%**  
- Exact-chunk Recall@5 = **92.5%**

---

## 11. Generation / RAG

### Transition
Retrieval finds evidence → LLM writes an English answer **from that evidence**.

```
Question
  → E5 + FAISS
  → Top-5 evidence chunks (TEXT)
  → Prompt template
  → LLM
  → Grounded English answer
```

**Critical:** The LLM receives **original English text**, not FAISS vectors.

### Actual prompt retained (`gita_rag_prompt.txt` — Step 14)

```
You are a Bhagavad Gita question-answering assistant.

Answer the user's question using ONLY the supplied Bhagavad Gita evidence.
Do not use outside knowledge.
If the supplied evidence does not contain enough information to answer the question, say that the retrieved evidence is insufficient.
Do not invent verses, quotations, explanations, or citations.
Answer in clear English.
Cite the Bhagavad Gita verse/source supporting the answer.
When relevant, distinguish between the verse translation and the purport/commentary.
Do not claim that something appears in the verse itself if it appears only in the purport.

Question:
{question}

Retrieved evidence:
{context}

Answer the question using only the evidence above.
```

Evidence blocks look like `[EVIDENCE i] / Citation / Section / Chunk ID / Text`.

---

## 12. FLAN-T5-small

**Script:** `gita/rag_generate.py`  
**Reports:** `gita_generation_smoke_report.json`, Step-14 manual labels in `gita_generation_step14_qwen_report.json`

| Item | Value |
|---|---|
| Model | `google/flan-t5-small` |
| Why tried | Small local instruction model already in Hugging Face cache; first generation smoke test |
| Context limit | **512** input tokens (severe for Top-5 evidence) |
| Settings | temperature 0, greedy, max_new_tokens 192 |
| Test | **10** smoke questions + insufficient-context control |
| Retriever | Frozen plain E5 Top-5 |

### Manual labels (same 10 questions; labeled in Step 14)

| Metric | FLAN |
|---|---:|
| Correct | **0** |
| Partially Correct | **1** |
| Wrong | **9** |
| Fully Grounded | 0 |
| Partially Grounded | 2 |
| Unsupported | 8 |
| Citation Correct | 0 |
| Citation Missing | 10 |

### Failure examples
1. **Q:** “What does Bhagavad Gita 2.47 say?” → FLAN answered with unrelated 2.49-ish surrender text (Wrong).  
2. **Q:** leaf/water offering with love → FLAN echoed prompt fragment: “Bhagavad Gita verse/source supporting the answer.” (Wrong).  
3. Bharata/deer purport question → FLAN only: “a deer” (Partial).

### Lesson
FLAN-T5-small’s **512-token window** and weak instruction following made it unsuitable for multi-chunk grounded RAG. Need a larger-context generator.

---

## 13. Qwen2.5 3B + Ollama

**Scripts:** `rag_generate_step14_qwen.py`, later `evaluate_generation_step16.py`  
**Report:** `gita_generation_step14_qwen_report.json`

| Item | Value |
|---|---|
| Why selected | Local development generator that fits Apple M3 16 GB; complete RAG without cloud APIs |
| LLM | **Qwen2.5 3B** (`qwen2.5:3b`) |
| Runtime | **Ollama 0.33.0** (NOT the LLM—only the local inference host) |
| Quantization / size | Q4_K_M; ~**1.9 GB** on disk; ~2.2 GB loaded; **3.1B** parameters |
| Context used | `num_ctx=8192` (model card allows 32768) |
| Temperature | **0** |
| Max output | `num_predict=512` |
| Seed | 0 |
| Hardware | **Apple M3**, **16 GB** unified memory, Apple Silicon / **Metal GPU** |
| GPU acceleration | Verified: `ollama ps` showed **100% GPU**, CONTEXT 8192 |
| CUDA | Not available / not used |

### Step-14 results (same 10 smoke questions as FLAN)

| Metric | Qwen | FLAN |
|---|---:|---:|
| Correct | **8** | 0 |
| Partially Correct | **1** | 1 |
| Wrong | **1** | 9 |
| Fully Grounded | **8** | 0 |
| Partially Grounded | 1 | 2 |
| Unsupported | 1 | 8 |
| Citation Correct | **8** | 0 |
| Citation Missing | 2 | 10 |

Insufficient-context control: Qwen correctly refused; FLAN did not.

**Direct comparison:** Same questions, same Top-5 evidence; only the generator changed. Qwen dramatically outperformed FLAN.

---

## 14. Prompt experiment (Step 15)

**Only change:** longer/more detailed grounding prompt (`gita_rag_prompt_step15.txt`).  
**Same:** E5 Top-5, Qwen2.5 3B, temperature 0, num_ctx 8192.

| Metric | Step 14 prompt | Step 15 prompt |
|---|---:|---:|
| Correct | **8** | 7 |
| Partial | 1 | 2 |
| Wrong | 1 | 1 |
| Fully Grounded | **8** | 7 |
| Control invented citation | No | **Yes** (failed control) |

**Finding:** More detailed prompting did **not** automatically improve performance (one regression; control broke).  
**Retained prompt:** **Step 14** (`gita_rag_prompt.txt`).

---

## 15. Fresh 40-question end-to-end test (VERY IMPORTANT)

**Files:**  
- Questions: `gita_generation_eval_frozen.json`  
- Validation: `gita_generation_eval_validation.json`  
- Results: `gita_generation_step16_results.json`  
- Report: `gita_generation_step16_report.json`

### Frozen evaluation design
| Item | Value |
|---|---|
| Total questions | **40** |
| Categories | 8 citation, 8 factual, 8 conceptual, 8 purport, 8 terminology |
| Difficulty | 10 easy, 18 medium, 12 hard |
| Chapter coverage | **All 18 chapters** |
| Overlap with prior retrieval gold sources | None (by design) |
| Smoke-set gold sources banned | Yes |
| Created before retrieval | Yes |
| Retriever | Plain E5 Top-5 |
| Generator | Qwen2.5 3B + Step 14 prompt |
| Truncation of Top-5 evidence | **None** (all Top-5 supplied for all 40) |

### Retrieval on this generation set
| Metric | Value |
|---|---:|
| Source Recall@1 | **0.90** (90%) |
| Source Recall@5 | **1.00** (100%) |
| Exact Chunk Recall@1 | **0.85** (85%) |
| Exact Chunk Recall@5 | **0.925** (92.5%) |

### Qwen generation (manual labels)
| Metric | Count | % of 40 |
|---|---:|---:|
| Correct | **29** | **72.5%** |
| Partially Correct | **9** | 22.5% |
| Wrong | **2** | 5.0% |
| Fully Grounded | **30** | 75.0% |
| Partially Grounded | **8** | 20.0% |
| Unsupported | **2** | 5.0% |
| Citation Correct | **25** | 62.5% |
| Citation Missing | **15** | 37.5% |
| Section Correct | **36** | 90.0% |
| Section Wrong | **2** | 5.0% |
| Section N/A | **2** | 5.0% |

### Main conclusion
**Retrieval is largely solved** on this set (Source Recall@5 = 100%).  
**Main bottleneck = generation:** instruction following, citations, occasional refusal/misread of available evidence (`main_bottleneck`: `generation_instruction_following_and_citations`).

### Representative failures
1. **Wrong / retrieval miss (`gita_gen_eval_029`):** Gold purport not in Top-5; model invented term “bhajati” (Unsupported).  
2. **Wrong / generation failure (`gita_gen_eval_030`):** Gold purport **was** rank 1; model incorrectly said evidence was insufficient.  
3. **Partial (`gita_gen_eval_003`):** Named lotus comparison but omitted “untouched by water.”  
4. **Partial (`gita_gen_eval_004`):** Quoted half of 8.16 then falsely claimed Krishna’s abode was missing from the same verse.

---

## 16. Model comparison table

| Model | Local/Cloud | Test size | Correct | Partial | Wrong | Context limitation | Main observation |
|---|---|---:|---:|---:|---:|---|---|
| FLAN-T5-small | Local (HF cache) | **10** smoke | 0 | 1 | 9 | **512** tokens | Too small; echoes / wrong answers |
| Qwen2.5 3B (Ollama) | Local (Metal GPU) | **10** smoke (same as FLAN) | 8 | 1 | 1 | 8192 used | Working local baseline |
| Qwen2.5 3B (Ollama) | Local | **40** fresh E2E | 29 | 9 | 2 | 8192; no Top-5 trunc. | Strong; citation gaps remain |
| Llama 3.2 3B | — | — | — | — | — | — | **Planned local comparison — NOT run yet** |

**Do not mix 10-q and 40-q rows as if they were the same test.**

---

## 17. Current hardware

Observed development machine (from Step 14 setup / system inspection):
- **Apple M3**
- **16 GB** unified memory
- Apple Silicon **GPU / Metal** (Ollama used 100% GPU)
- **No NVIDIA CUDA GPU**

**Why this limits 24B–30B models:** Larger models need much more VRAM/unified memory for comfortable context + weights. 16 GB is workable for ~3B quantized models, not comfortable for 24B–30B instruct models with long Top-5 evidence prompts.

---

## 18. Proposed next experiment (NOT performed)

**Keep frozen:**
- E5 + FAISS + 1443 chunks + Top-5 + evaluation methodology / frozen questions

**Change ONLY:** generator (larger model)

**Candidate models (proposed):**
- Qwen3 30B-A3B Instruct  
- Mistral Small 3.2 24B  

**Proposed hardware:** NVIDIA **L40S 48 GB** or better (cloud / university server)

**Status:** Proposal only — **do not claim completed**.

---

## 19. Demo preparation (documentation only — nothing built)

### What exists today
- `rag_generate.py`: E5 retrieve + FLAN smoke (`--smoke` only). **No interactive ask CLI.**  
- `rag_generate_step14_qwen.py` / `evaluate_generation_step16.py`: batch Qwen over saved/frozen questions.  
- Reusable pieces already inside `rag_generate.py`: `E5Retriever.retrieve()` + context builder; Qwen call pattern in Step 14/16 scripts + `gita_rag_prompt.txt`.

### Easiest demo tomorrow
**Option A (smallest safe wrapper — not built yet):** ~20–40 lines that:
1. Load `E5Retriever` from existing code  
2. `retrieve(question, top_k=5)`  
3. `build_context(hits)`  
4. Call Ollama `qwen2.5:3b` with Step 14 prompt  
5. Print Top-5 (source + section + score) then the answer  

**Option B (no new code):** Manually pick a frozen Step-16 question and show saved `retrieval_top5` + `generated_answer` from `gita_generation_step16_results.json` (offline demo). Less impressive live, but zero risk.

**Prerequisite:** Ollama running with `qwen2.5:3b` pulled.

### Recommended demo questions (from existing corpus/eval style)
1. **Direct verse:** “What does Bhagavad Gita 2.47 say?”  
2. **Conceptual:** “In what way can a person’s own mind be their friend, and in what way can it be their enemy?”  
3. **Purport/commentary:** “What example does the commentary give of a king whose last thought was an animal, and what body did he get next?”  
4. **Terminology:** “How does this Gita distinguish sannyasa, the renounced order, from tyaga, renunciation?”  
5. **Factual offering:** “If a person offers Krishna something as simple as a leaf or a little water, but with love, does the Gita say He accepts it?”

---

## 20. Visualizations for PowerPoint

Created under `gita/presentation_assets/`:

| File | Content |
|---|---|
| `retrieval_results_comparison.png` | E5 vs BM25 vs Hybrid on 30-q and held-out 40-q (source-level) |
| `generator_comparison.png` | FLAN vs Qwen on **same 10** smoke questions (sample sizes equal here) |
| `qwen_40_generation_results.png` | Correct / Partial / Wrong and grounding on **40** E2E |
| `pipeline_flowchart.png` | PDF → … → Qwen → answer |
| `project_statistics.png` | 1051 / 18 / 700 / 657 / 1443 (confirmed) |

---

## 21. IMPORTANT CODE SNIPPETS FOR PROFESSOR

### 1) PDF extraction — `extract_chapter.py`
```python
TEXT_HEADING_RE = re.compile(
    r"^(TEXTS?)\s+(\d+)(?:\s*[–—-]\s*(\d+))?\s*$",
    re.MULTILINE,
)
reader = PdfReader(str(pdf_path))
for i, page in enumerate(reader.pages):
    text = COPYRIGHT_RE.sub("", page.extract_text() or "")
    pages.append((i + 1, text))
```
Finds verse blocks by TEXT/TEXTS headings after reading all PDF pages as text.

### 2) Chunking — `chunker.py`
```python
TARGET_PURPORT_WORDS = 350
OVERLAP_WORDS = 40
trans_text = f"{cite} — Translation\n\n{record['translation'].strip()}"
parts = split_purport(record["purport"])  # split only if long
```
Keeps translations whole; splits long purports with overlap for E5’s length limit.

### 3) E5 embedding — `build_e5_index.py`
```python
inputs = ["passage: " + c["text"] for c in chunks]
embeddings = model.encode(inputs, normalize_embeddings=True, device="cpu")
```
Turns each chunk into a normalized 1024-dim meaning vector.

### 4) FAISS indexing — `build_e5_index.py`
```python
index = faiss.IndexFlatIP(dim)
index.add(embeddings)
faiss.write_index(index, str(args.index))
```
Stores all 1443 vectors for exact similarity search.

### 5) FAISS query/search — `evaluate_e5.py` / `rag_generate.py`
```python
q = model.encode(["query: " + question], normalize_embeddings=True, ...)
scores, rows = self.index.search(q, top_k)
```
Embeds the question and returns the nearest chunk rows.

### 6) Top-5 context construction — `rag_generate.py`
```python
block = (
    f"[EVIDENCE {i}]\n"
    f"Citation: {citation_label(hit)}\n"
    f"Section: {section_label(hit)}\n"
    f"Chunk ID: {hit['chunk_id']}\n"
    f"Text:\n{body.strip()}\n"
)
```
Formats retrieved English text (not vectors) for the LLM.

### 7) Qwen/Ollama generation — `rag_generate_step14_qwen.py` / Step 16
```python
# Ollama chat with qwen2.5:3b, temperature=0, num_ctx=8192, num_predict=512
# User message = Step-14 prompt with {question} and {context}
```
Runs the local LLM on the evidence prompt; Ollama is the runtime, Qwen is the model.

### 8) Evaluation — `evaluate_e5.py` pattern
```python
gold_sources = {g["source_record_id"] for g in q["gold_sources"]}
gold_chunks = {cid for g in q["gold_sources"] for cid in g["gold_chunk_ids"]}
source_rank = first_gold_rank(retrieved_source_ids, gold_sources)
chunk_rank = first_gold_rank(retrieved_chunk_ids, gold_chunks)
```
Scores retrieval with frozen gold labels **after** search (labels never enter the query).

---

## 22. Final project file map

| Phase | Important file | Purpose |
|---|---|---|
| Source PDF | `data/Bhagavad-gita_As_It_Is.pdf` | Input book |
| Extraction | `gita/extract_chapter.py` | PDF → structured verse JSON |
| Structured corpus | `gita/gita_structured.json` | 657 verse records |
| Extraction validation | `gita/gita_validation.json` | 700 verses / chapter checks |
| Chunking | `gita/chunker.py` | Records → retrieval chunks |
| Chunks | `gita/gita_chunks.json` | 1443 chunks |
| Chunk validation | `gita/gita_chunk_validation.json` | Chunk design checks |
| Embed + index | `gita/build_e5_index.py` | E5 + FAISS build |
| FAISS index | `gita/gita_e5.faiss` | 1443 vectors |
| Index metadata | `gita/gita_e5_metadata.json` | row → chunk text/ids |
| Truncation report | `gita/gita_e5_truncation_report.json` | 221 over 512 tokens |
| Frozen 30-q | `gita/gita_eval_frozen.json` | Retrieval dev questions |
| E5 eval | `gita/gita_e5_eval_summary.json` | 30-q E5 metrics |
| BM25 eval | `gita/gita_bm25_eval_summary.json` | 30-q BM25 metrics |
| Hybrid eval | `gita/gita_hybrid_rrf_eval_summary.json` | 30-q RRF metrics |
| Holdout 40-q | `gita/gita_holdout_frozen.json` | Held-out retrieval set |
| Holdout results | `gita/gita_holdout_eval_summary.json` | Fresh retrieval comparison |
| FLAN smoke | `gita/rag_generate.py` + smoke report/results | Generator #1 |
| Prompt | `gita/gita_rag_prompt.txt` | Retained grounding prompt |
| Qwen Step 14 | `gita/rag_generate_step14_qwen.py` + report | Generator #2 (10-q) |
| Prompt Step 15 | `gita/gita_rag_prompt_step15.txt` + report | Prompt-only experiment |
| Gen eval 40-q | `gita/gita_generation_eval_frozen.json` | Fresh E2E questions |
| Step 16 eval | `gita/evaluate_generation_step16.py` + report/results | Full E2E metrics |
| Presentation assets | `gita/presentation_assets/*.png` | Slide figures |
| This handoff | `gita/PRESENTATION_HANDOFF.md` | ChatGPT input |

---

## 23. Compact executive summary for slides

1. **Problem:** English Q&A over Bhagavad Gita PDF without hallucinated verses.  
2. **Data:** ~1051-page PDF → 18 chapters → **700** verses in **657** records → **1443** chunks.  
3. **Retrieve:** E5 (1024-d) + FAISS; held-out Source Recall@5 = **100%**.  
4. **Baselines:** BM25 and Hybrid RRF tested; **plain E5 kept**.  
5. **Generate:** FLAN-T5-small failed (0/10 correct); **Qwen2.5 3B** works (8/10 smoke; **29/40** correct E2E).  
6. **Bottleneck now:** Generation/citations, not retrieval.  
7. **Next (proposed):** Same pipeline, larger generator on cloud GPU — **not run yet**.

---

## Files to give ChatGPT for the PowerPoint

**Minimum (enough for slides):**
1. `gita/PRESENTATION_HANDOFF.md` ← **primary**
2. `gita/presentation_assets/retrieval_results_comparison.png`
3. `gita/presentation_assets/generator_comparison.png`
4. `gita/presentation_assets/qwen_40_generation_results.png`
5. `gita/presentation_assets/pipeline_flowchart.png`
6. `gita/presentation_assets/project_statistics.png`

**Optional supporting metrics files (if ChatGPT wants to double-check numbers):**
- `gita/gita_validation.json`
- `gita/gita_chunk_validation.json`
- `gita/gita_e5_eval_summary.json`
- `gita/gita_bm25_eval_summary.json`
- `gita/gita_hybrid_rrf_eval_summary.json`
- `gita/gita_holdout_eval_summary.json`
- `gita/gita_generation_step14_qwen_report.json`
- `gita/gita_generation_step15_report.json`
- `gita/gita_generation_step16_report.json`
- `gita/gita_rag_prompt.txt`

**Do not need** to upload the full FAISS index, full `gita_chunks.json`, or multi-hundred-KB result dumps unless asked.

---

*End of handoff. No RAG implementation files were modified to produce this report; only `gita/presentation_assets/` and this markdown were added.*
