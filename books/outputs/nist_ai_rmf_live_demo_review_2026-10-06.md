# NIST AI RMF PDF — live BookRAG demo review (2026-10-06)

## Scope

Tested `sample_pdfs/nist-ai-rmf-1.0.pdf` against the live local demo at `http://127.0.0.1:5055/`. This was an exploratory browser check, not a frozen retrieval evaluation. No search settings, answer prompts, or source code were changed.

The browser's file chooser did not complete in this automation session, so I attached the PDF through the demo's existing local `/attach` endpoint, reloaded the browser, and asked every question in the browser UI. Findings about attachment display after reload are specific to that path; normal file-picker upload was not verified.

Attachment succeeded: 48 PDF pages with text, 81 indexed passages, about 57.1 seconds total. The book remained attached in the browser. The reported indexing stages were text extraction 0.83 s, chunking 0.36 s, storage 0.07 s, BGE-M3 meaning indexing 25.04 s, and word indexing 30.81 s. The last two stages dominate indexing time.

## Browser questions and observed results

| Question | Observed answer | Evidence shown in UI | Total wait | Judgment |
| --- | --- | --- | ---: | --- |
| Four Core functions? | GOVERN, MAP, MEASURE, MANAGE | Passage 37, PDF p. 25 | 15.00 s | Correct; supporting text visible |
| Is GOVERN one-time or ongoing? | Ongoing and applies across the other functions | Passages 37 and 40, PDF pp. 25 and 27 | 16.29 s | Correct; both passages support the answer |
| Required checklist or fixed sequence? | No; actions are neither a checklist nor necessarily ordered | Passage 37, PDF p. 25 | 16.39 s | Correct; exact sentence visible |
| What costs does MAP 3.2 examine? | Potential costs, including non-monetary costs from AI errors or system function/trustworthiness, related to risk tolerance | Passage 50, PDF p. 32 | 15.91 s | Correct; wording matches the passage |
| What does MEASURE 2.7 evaluate? | AI system security and resilience identified in MAP | Passage 56, PDF p. 35 | 12.86 s | Correct; wording matches the passage |
| What fine must a company pay for violating the AI RMF? | Supplied passages do not establish a fine or whether one applies | No citation | 14.62 s | Appropriate refusal; no amount invented |

These six questions are a small, selected check. Five matching answers do not establish an overall accuracy percentage or prove that other NIST questions will work.

## Confirmed issue

**Attachment progress does not restore after page reload.** After the PDF was attached through `/attach` and the browser was reloaded, the library correctly showed it as `ATTACHED` and questions worked. Yet the “Attach pipeline” card still said “Attach a PDF to run the pipeline,” and the combined time card showed only the latest answer time, omitting the measured ~57-second indexing time. The page initializes `lastAttachSeconds` to `null` and renders the default attach message; it fills the indexing duration only in the file-input `change` handler after a same-page upload. The `/attach/status` route exists but the page only polls it during upload. This is a presentation/state restoration issue; indexing and answering succeeded. It could mislead a professor about whether the PDF was processed and about end-to-end time.

**Suggested fix:** on page load, when a book is attached, fetch its attach status and saved indexing duration (or expose these in the initial page data), mark the completed stages, and distinguish `Index time` from `Latest answer time`. Keep the state accurate after reload and after a direct attach.

## Observed limitations, not answer errors

- **Question latency:** 12.9–16.4 seconds each. Qwen reranking took about 7.6–8.8 seconds in these six runs, the largest single part of most waits. This is okay for a guided demo if the presenter sets expectations, but feels slow for free-form browsing.
- **Excerpt header noise:** the evidence pane showed lines such as `25 nist ai rmf 1.0` before the useful sentence. The answer text itself remained clean. Display-only removal of repeated headers would improve readability.
- **No fixed test set:** the questions above were chosen because the PDF contains clear answers. Include harder wording, cross-page answers, and deliberately absent facts in a future frozen evaluation before claiming general NIST performance.

## Recommended next actions

1. Fix restored attach progress and timing after reload; this is the one confirmed UI defect from this check.
2. In the demo, explain that attaching this 48-page PDF took about 57 seconds once, while questions took about 13–16 seconds each.
3. Before broader claims, freeze a NIST question set and compare whether the correct passage reached the 20 candidates, the five passages sent to Sol, and the final cited answer. Keep the original answers and indexes as baselines.

The NIST PDF was attached for this test and was not removed. This report adds a new file only.
