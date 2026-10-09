# USGS OCR experiment + UI fixes — report (2026-10-07)

## Simple summary

1. **UI:** After reload with a book attached, the answer area now says **“Ask a question about this PDF.”** instead of “Upload a PDF first.”
2. **Timing:** Fast re-attach is labeled separately from the original one-time indexing time.
3. **OCR experiment:** Local Tesseract can read the page-21 caption into a **separate** experimental index, but the usual question *“What … on PDF page 21?”* still does **not** retrieve that passage or answer with a correct citation. **Do not turn OCR on in the live demo yet.**

## What changed (live demo)

| File | Why |
| --- | --- |
| `books/demo/templates/index.html` | Attached-book placeholder; clearer original / re-attach / question timings |
| `books/demo/pipeline.py` | Persist `reuse_attach` + reuse flags on `/ready` for reload |

**Unchanged:** BGE-M3 → hybrid top 20 → local Qwen → top 5 → Sol.

## Browser checks

- Reloaded with USGS attached: book, completed stages, and one-time indexing restored.
- Answer placeholder: **“Ask a question about this PDF.”**
- Same-PDF re-attach via `/attach`: ~0.07 s reuse; original index total kept as 32.98 s.
- File-picker automation was **not** verified (tool limit). App `/attach` upload works.

## Reuse key behavior (reported before changing it)

Current book id = `live_{filename_stem}_{sha256(pdf)[:8]}`.

- Same bytes + same filename → stable id → **reuses** index.
- Same bytes + **different filename** → different id → **does not reuse** (would re-index).

Recommendation: keep as-is for now (safe). A later content-hash-only lookup could reuse across filenames without risking different content.

## OCR experiment (separate from live demo)

Local tools used: **Tesseract + Poppler + pdf2image** (no API OCR cost).

General rule: OCR only pages whose ordinary extract has **&lt; 80 letters**.

USGS low-text pages: **1, 2, 21, 23, 25, 40**.

Artifacts (do not overwrite baseline):

- `outputs/ocr_experiments/exp_usgs_volcanoes_ocr_v1/`
- `outputs/ocr_experiments/exp_usgs_volcanoes_ocr_v1b/` (stricter OCR line cleaning)
- Frozen questions: `outputs/usgs_volcanoes_frozen_cases.json`
- Comparison: `outputs/ocr_experiments/exp_usgs_volcanoes_ocr_v1/usgs_ocr_v1_comparison.json`

### Page 21 caption

Visible caption: **“Mount St. Helens, about noon, May 18, 1980.”**  
OCR recovered (noisy): **“Mount St. Heléns, about noon, May, 18, 1980”**.

| System | Page 21 in hybrid 20? | In Qwen top 5? | Correct cited answer? |
| --- | --- | --- | --- |
| Baseline text | No | No | No (honest refusal) |
| OCR v1 | No | No | No |
| OCR v1b (cleaner) | No for “photograph on PDF page 21?” | No | No |
| OCR v1b with caption-like query (“Mount St. Helens … 1980”) | **Yes (rank 1)** | **Yes** | (retrieval only) |

So OCR **stores** the caption, but a **page-number photo question** still misses it. Caption-like wording finds it. That is a retrieval/question-form limit, not “OCR failed to read the page.”

### Other frozen USGS checks

- Four volcano types / shield / geysers / monitoring: text pages still retrieve correctly on OCR index (spot-checked four types with Sol: correct, PDF page 10).
- Current-alert question: both baseline and OCR **appropriately refuse**.
- Page 23 Paricutin / Vesuvius: already partly in baseline extract; both can answer. OCR v1 Vesuvius hit a **quote-check soft fail** from OCR noise (extra warning) — a new risk if OCR is enabled carelessly.

### Cost / time

- OCR of 6 pages: ~5 s
- Experimental re-embed: ~43–56 s (separate index)
- Disk: experimental chunk + report trees under `outputs/ocr_experiments/`
- Sol for this comparison: **about $0.11 estimated** (plus a small follow-up page-21 ask on v1b)

## NIST / Apollo regressions

The frozen 12 NIST/Apollo cases were **not** re-scored in this pass (spend control). USGS text questions that overlap the live review still looked stable.

## Recommendation

**Keep the live demo on text-only indexing.**

Enable OCR only after a measured design for:

1. cleaner OCR text,
2. page-aware retrieval for “what’s on page N?” questions, and/or
3. a separate visual path for charts/photos (OCR ≠ understanding images).

## Limits that remain

- Image captions may be invisible to ordinary PDF text extraction.
- OCR is imperfect (accents, digits, speckles) and can hurt quote verification.
- “What’s on page N?” questions need more than dumping OCR into the same hybrid index.
- First-time indexing is still dominated by BGE-M3.
