"""One claimed job: PDF extraction, hosted embeddings, then atomic index publication."""
from uuid import UUID

from .chunking import extract_chunks
from .config import Settings
from .providers import HostedModels
from .repository import Repository
from .storage import PrivateStorage


def ingest_document(document: dict, repo: Repository, storage: PrivateStorage, models: HostedModels, cfg: Settings):
    document_id: UUID = document["id"]
    owner: UUID = document["owner_id"]
    data = storage.download(document["storage_path"])
    if len(data) > cfg.max_pdf_bytes:
        raise ValueError("PDF exceeds the size limit")
    page_count, rows = extract_chunks(data, cfg.max_pdf_pages, cfg.max_passages)
    if not repo.job_document(document_id):
        return
    repo.mark_processing(document_id)
    token_total = 0
    for start in range(0, len(rows), 32):
        batch = rows[start:start + 32]
        vectors, tokens = models.embed([r["text"] for r in batch], "document")
        for row, vector in zip(batch, vectors):
            row["embedding"] = vector
        token_total += tokens
    saved = repo.store_passages(owner, document_id, rows, page_count)
    if saved:
        repo.record_usage(owner, document_id, "embedding", "voyage-4-large", token_total, 0, token_total * .12 / 1_000_000)
