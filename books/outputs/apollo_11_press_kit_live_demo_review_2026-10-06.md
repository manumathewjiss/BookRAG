# Apollo 11 press kit — live BookRAG demo check (2026-10-06)

## What was tested

Tested `books/sample_pdfs/nasa-apollo-11-press-kit.pdf` in the local BookRAG demo at `http://127.0.0.1:5055/`. This scanned 1969 press kit is a different challenge from the clean NIST PDF: its extracted text includes stray characters, broken words, and image-heavy pages.

The browser file chooser did not complete in this automation session, so the PDF was attached through the demo's existing local `/attach` endpoint. The browser was reloaded and all six questions were then asked in its UI. This is an exploratory check, not a frozen evaluation. No source code, search settings, or answer prompts were changed.

The demo indexed **341 passages from 254 PDF pages** in **177.3 seconds**. Text extraction took 4.1 s, chunking 0.7 s, storage 0.1 s, BGE-M3 meaning indexing 71.4 s, and word indexing 100.9 s. The PDF remains indexed and attached; the previous NIST upload was not deleted, but the desk shows only one attached book at a time.

## Browser results

| Question | What the demo answered | Evidence shown | Wait | Assessment |
| --- | --- | --- | ---: | --- |
| Stated prime mission objective? | Perform a manned lunar landing and return | Passage 6, PDF p. 7 | 12.72 s | Correct |
| Words on the lunar module plaque? | Full inscription ending “WE CAME IN PEACE FOR ALL MANKIND” | Passage 5, PDF p. 6 | 11.55 s | Correct |
| Lunar television camera frame rate and resolution? | 10 frames per second; 320 lines per frame | Passage 90, PDF p. 81 | 12.30 s | Correct |
| Planned crew recovery after splashdown? | Isolation garments, helicopter to Hornet, Mobile Quarantine Facility, then Lunar Receiving Laboratory; 21-day quarantine from lunar liftoff | Passage 74, PDF p. 69 | 12.07 s | Correct, all details on cited page |
| Did this press kit confirm a successful landing or precede the mission? | It was written beforehand and describes a planned launch | Passage 4, PDF p. 5 | 12.05 s | Correct; did not turn a forecast into an outcome |
| What does the press kit prove about the actual outcome after the mission? | The supplied passages cannot prove the eventual outcome | Related passages, including passage 6, PDF p. 7 | 13.25 s | Appropriate qualification/refusal |

The average wait across these six browser questions was about **12.3 seconds**. Qwen reranking took roughly **7.6–8.7 seconds**, the largest part of the wait. Six hand-picked questions cannot establish an overall accuracy rate.

## Weaknesses seen

1. **The attach card and combined timer remain misleading after reload.** The browser showed the press kit as `ATTACHED` and answered questions, but the card said “Attach a PDF to run the pipeline.” The time card showed only the last answer and omitted the measured 177-second indexing step. This repeats the NIST finding. It is specifically verified after a direct `/attach` call followed by page reload; the normal browser file-picker path was not verified.
2. **Scan noise reaches the evidence display.** The PDF page 7 excerpt starts with stray characters (`a I I I ...`) before the mission objective. Page 81 shows `frames-persecond`. The answers themselves were clean in these tests. Display-only cleanup could hide noise, while keeping the original full passage and real PDF available.
3. **Indexing is noticeable for a new scanned book.** This press kit took nearly three minutes before it could answer. Most of the time was BGE-M3 indexing. For a live presentation, attach and index the PDF in advance, or clearly show progress.

## Suggested order

First fix the restored attach status and timer after reload. Next improve display cleanup for scan artifacts, with the original text still accessible. For stronger accuracy claims, freeze a larger Apollo question set that includes tables, diagrams, repeated facts, and questions the pre-launch document cannot answer.

No existing evaluation files were overwritten. This report is a new file only.
