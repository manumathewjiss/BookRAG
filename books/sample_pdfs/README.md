# Sample PDFs for Stage 1

Put **one digital-text PDF** in this folder (text you can select/copy in a PDF reader).

```
books/sample_pdfs/your-book.pdf
```

Requirements:

- Digital text, **not** a scanned image of pages
- **Not** `Bhagavad-gita_As_It_Is.pdf` or other Gita edition files
- No OCR in Stage 1

A short public-domain ebook or a born-digital paper (about 10–40 pages) is enough.

## Tracked in git

- `pride-and-prejudice.pdf` — Jane Austen, public domain (Planet eBook edition)
- `thinkpython.pdf` — Allen B. Downey, *Think Python* 2.0.17, [CC BY-NC 3.0](https://creativecommons.org/licenses/by-nc/3.0/)

Kept only on this machine:

- `Bhagavad-gita_As_It_Is.pdf` — copyrighted evaluation copy (Bhaktivedanta Book Trust, 1972–2004)
- `arthashastra.pdf` — local Safari export of a Temple Library session, not a source edition

Then run from the repo root:

```bash
source ~/.venvs/pramod-books-rag/bin/activate
python books/ingest_stage1.py --pdf books/sample_pdfs/your-book.pdf
```
