# USGS *Volcanoes* PDF — live BookRAG review (2026-10-06)

## Scope

Tested `books/sample_pdfs/usgs-volcanoes.pdf` in the local browser demo at `http://127.0.0.1:5055/`. This 41-page illustrated USGS booklet tests a different PDF layout from NIST and the Apollo press kit. The browser file chooser did not complete in this automation session, so I attached the file through the demo's existing local `/attach` endpoint, reloaded the browser, and asked all six questions through the visible demo UI. Normal file-picker upload was not verified here. No pipeline source or settings were changed.

The demo indexed **54 passages from 41 PDF pages** in **32.98 seconds**: extraction 1.45 s, chunking 0.15 s, storage 0.08 s, BGE-M3 meaning indexing 14.99 s, and word indexing 16.29 s. After reload, the attach stages and one-time indexing time **were correctly restored**. This fixes the main reload/timing problem observed in the earlier NIST and Apollo checks.

## Browser questions

| Question | Browser result | Evidence | Wait | Review |
| --- | --- | --- | ---: | --- |
| Four main kinds of volcanoes? | Cinder cones, composite volcanoes, shield volcanoes, lava domes | Passage 11, PDF p. 10 | 14.29 s | Correct |
| Why are shield volcanoes broad and gently sloping? | Fluid basaltic lava spreads far, then cools in thin layers over many flows | Passage 17, PDF p. 16 | 13.62 s | Correct |
| Why do geysers and hot springs occur near young volcanoes? | Water seeps toward hot magma, heats, rises; a geyser can eject water when some flashes to steam | Passage 34, PDF p. 28 | 13.34 s | Correct |
| What visible changes do scientists watch between eruptions? | Changes in steaming, cracks, plant health, and mineral-deposit color | Passage 45, PDF p. 36 | 14.86 s | Correct |
| Which volcano is erupting **today**, and at what alert level? | Cannot establish current activity or alert level from this booklet; it only refers to Mount St. Helens as of June 1981 | Related passage 49, PDF p. 38 | 14.09 s | Appropriate refusal and date distinction |
| What volcano and date are shown in the photograph on **PDF page 21**? | Supplied passages do not identify them | No cited passage | 15.40 s | Honest refusal, but a real document-coverage miss |

The six waits averaged about **14.3 seconds**. Local Qwen reranking took about **8–9 seconds** on each question and was the main part of the question wait. These are six selected probes, not an overall accuracy rate.

## Main finding: picture-only information is missing

PDF page 21 visibly contains a large eruption photograph. Its caption, visible on the PDF page, reads **“Mount St. Helens, about noon, May 18, 1980.”** Yet ordinary text extraction from that page returned only the printed page numbers (`23 22`). The caption did not enter the searchable passages. The demo therefore could not answer the page-specific photo question. This is an **input coverage problem**, not evidence that the answer model ignored a passage it received.

**Recommended experiment:** detect pages with very little extractable text, run OCR on those pages or on their captions, save the recovered text with its original PDF page number, then test the same frozen questions before changing production indexing. OCR should be treated as text recognition, not as a guarantee that the system understands a chart or image. For genuinely visual questions, evaluate a vision-capable path separately. Keep the current text-only baseline for comparison and do not add a rule specific to this volcano or page.

## Smaller UI issue

Immediately after reload, the book was marked `ATTACHED` and the indexing panel correctly said `Indexed 54 passages from 41 PDF pages`, but the empty answer panel still said **“Upload a PDF first.”** Once a question was asked, that placeholder disappeared. Change that placeholder to an attached-book message such as “Ask a question about this PDF.” This is a display issue, not an indexing failure.

## Suggested order

1. Fix the attached-book answer placeholder.
2. Add a general low-text-page detector and perform a controlled OCR test on this booklet and other illustrated PDFs. Measure whether it recovers the page-21 caption without creating bad text or wrong citations.
3. If the product needs answers about charts and photographs themselves, design and evaluate a separate visual retrieval/answer route. Do not claim that the current text-only route covers those pages.
4. Keep the existing citation and refusal behavior: the demo correctly avoided inventing current alert information and photo details it could not read.

The USGS book remains attached. This is a new review file; existing evaluation files were not overwritten.
