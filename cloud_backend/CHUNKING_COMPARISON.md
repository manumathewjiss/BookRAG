# Uploaded PDF chunks versus the research benchmark

The live backend preserves the **PDF page reference** for every chunk. The extractor walks PDF pages in order and records `pdf_page=1,2,...`; chunks never cross a page boundary. The API takes citation pages from that stored field, not from Sol. Offline tests use a two-page PDF and verify that the answer about page 2 cites page 2.

| Detail | Frozen research Stage 1 | Cloud upload implementation |
| --- | --- | --- |
| PDF extractor | LangChain `PyPDFLoader`, page mode | `pypdf.PdfReader`, page by page |
| Text cleanup | NUL/whitespace normalization | Same light cleanup, adapted locally |
| Splitter | `RecursiveCharacterTextSplitter` with paragraph/line/sentence/word separators | Fixed token windows inside each PDF page |
| Token counter | `intfloat/multilingual-e5-large` tokenizer | `cl100k_base` tokenizer; no local model weights |
| Target | 450 content tokens, 50 overlap; hard E5 512 input-token check | 450 tokens, 50 overlap; Voyage request sets `truncation=false` |
| Page metadata | One-based PDF page | One-based PDF page |
| Chunk IDs | Sequential research `chunk_index` | Sequential index plus server-generated UUID |

The cloud chunks are **not identical** to the historical chunks. The frozen 150 and 32 question scores do not measure accuracy on newly uploaded PDFs. Before claiming equivalent accuracy, freeze a new uploaded-PDF question set and compare retrieval, answer support, and PDF citations. No local E5/Qwen model is loaded by the cloud service.
