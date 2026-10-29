"""Successful batches survive retries; ambiguous provider outcomes stop automatic calls."""
import hashlib
from uuid import uuid4

from bookrag_cloud.config import Settings
from bookrag_cloud.providers import ProviderError, ProviderRejected
from bookrag_cloud.worker import work_once
from tests.test_mocked_cloud_flow import MemoryRepository


def setup_job():
    owner, doc = uuid4(), uuid4()
    data = b"%PDF-test"
    repo = MemoryRepository()
    repo.create_document(owner, doc, "Test", "test.pdf", "owner/doc/source.pdf", hashlib.sha256(data).hexdigest(), 5)
    class Storage:
        def download(self, path): return data
    return repo, Storage(), doc


def rows(count):
    return [{"chunk_index": i, "pdf_page": 1 + i // 32, "text": f"passage number {i}"} for i in range(count)]


def test_definite_429_retries_only_unsaved_batch(monkeypatch):
    import bookrag_cloud.ingestion as ingestion
    repo, storage, doc = setup_job()
    monkeypatch.setattr(ingestion, "extract_chunks", lambda *args: (2, rows(33)))
    class Models:
        def __init__(self): self.calls = 0
        def embed(self, texts, mode):
            self.calls += 1
            if self.calls == 2:
                raise ProviderRejected(429)
            return [[1.0] * 1024 for _ in texts], len(texts) * 10
    models = Models()
    cfg = Settings()
    assert work_once(repo, storage, models, cfg) is True
    assert repo.jobs[doc]["status"] == "queued"
    assert repo.docs[doc]["status"] == "queued"
    assert repo.batches[(doc, 0)]["status"] == "complete"
    assert (doc, 1) not in repo.batches
    assert work_once(repo, storage, models, cfg) is True
    assert repo.docs[doc]["status"] == "ready"
    assert models.calls == 3  # first batch was reused; only second was resent
    assert len([event for event in repo.usages if event[1] == "embedding"]) == 2


def test_ambiguous_timeout_never_auto_retries(monkeypatch):
    import bookrag_cloud.ingestion as ingestion
    repo, storage, doc = setup_job()
    monkeypatch.setattr(ingestion, "extract_chunks", lambda *args: (1, rows(1)))
    class Models:
        def __init__(self): self.calls = 0
        def embed(self, texts, mode):
            self.calls += 1
            if self.calls == 1:
                raise ProviderError("request timed out after delivery")
            return [[1.0] * 1024], 10
    models = Models()
    assert work_once(repo, storage, models, Settings()) is True
    assert repo.jobs[doc]["status"] == "attention"
    assert repo.batches[(doc, 0)]["status"] == "pending"
    assert work_once(repo, storage, models, Settings()) is False
    assert models.calls == 1
    assert repo.clear_reviewed_batch(doc, 0) is True  # explicit operator resolution only
    assert work_once(repo, storage, models, Settings()) is True
    assert models.calls == 2 and repo.docs[doc]["status"] == "ready"


def test_checkpoint_refuses_changed_batch_input():
    repo, _, doc = setup_job()
    token = uuid4()
    repo.begin_embedding_batch(doc, token, 0, "original-digest")
    from bookrag_cloud.repository import UncertainEmbeddingBatch
    try:
        repo.begin_embedding_batch(doc, token, 0, "changed-digest")
    except UncertainEmbeddingBatch:
        pass
    else:
        raise AssertionError("Changed text must not reuse an earlier embedding")
