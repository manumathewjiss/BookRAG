"""One claimed job: deterministic batches, durable checkpoints, atomic index publication."""
import hashlib
import json
from uuid import UUID

from .chunking import extract_chunks
from .config import Settings
from .providers import HostedModels, ProviderRejected
from .repository import Repository, UncertainEmbeddingBatch
from .storage import PrivateStorage


def batch_digest(rows: list[dict]) -> str:
    payload = {"model": "voyage-4-large", "dimension": 1024, "mode": "document",
               "texts": [row["text"] for row in rows]}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def ingest_document(document: dict, claim_token: UUID, repo: Repository,
                    storage: PrivateStorage, models: HostedModels, cfg: Settings):
    document_id: UUID = document["id"]
    owner: UUID = document["owner_id"]
    data = storage.download(document["storage_path"])
    if len(data) > cfg.max_pdf_bytes:
        raise ValueError("PDF exceeds the size limit")
    if hashlib.sha256(data).hexdigest() != document["sha256"]:
        raise ValueError("Stored PDF no longer matches its upload")
    page_count, rows = extract_chunks(data, cfg.max_pdf_pages, cfg.max_passages)
    if not repo.job_document(document_id):
        return
    repo.mark_processing(document_id, claim_token)
    # Preserve the size of any completed checkpoint when resuming an older job.
    # New jobs use fewer provider requests without changing passage boundaries.
    batch_size = repo.embedding_batch_size(document_id) or 128
    expected_batches = (len(rows) + batch_size - 1) // batch_size
    for batch_index, start in enumerate(range(0, len(rows), batch_size)):
        batch = rows[start:start + batch_size]
        digest = batch_digest(batch)
        repo.renew_job_lease(document_id, claim_token)
        saved_vectors = repo.begin_embedding_batch(document_id, claim_token, batch_index, digest)
        if saved_vectors is None:
            try:
                vectors, tokens = models.embed([r["text"] for r in batch], "document")
            except ProviderRejected:
                repo.release_rejected_batch(document_id, claim_token, batch_index)
                raise
            repo.complete_embedding_batch(owner, document_id, claim_token, batch_index, digest, vectors, tokens)
        else:
            vectors = saved_vectors
        if len(vectors) != len(batch) or any(len(vector) != 1024 for vector in vectors):
            raise UncertainEmbeddingBatch("Saved embedding batch has invalid dimensions")
        for row, vector in zip(batch, vectors):
            row["embedding"] = vector
    repo.renew_job_lease(document_id, claim_token)
    repo.store_passages(owner, document_id, claim_token, rows, page_count, expected_batches)
