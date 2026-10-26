from uuid import uuid4

from bookrag_cloud.config import Settings
from bookrag_cloud.chunking import PasswordProtectedPdfError
from bookrag_cloud.worker import work_once


def test_worker_records_safe_failure_and_does_not_loop_forever(monkeypatch):
    doc = uuid4()
    class Repo:
        def __init__(self): self.failed = None; self.expired = 0
        def flag_stale_pending(self): pass
        def fail_exhausted_jobs(self): self.expired += 1
        def claim_job(self): return {"document_id": doc, "attempts": 1, "claim_token": uuid4()}
        def job_document(self, doc_id): return {"id": doc_id}
        def has_pending_batch(self, doc_id): return False
        def job_failure(self, doc_id, token, attempts, message): self.failed = (doc_id, attempts, message)
    repo = Repo()
    def broken(*args): raise RuntimeError("secret provider response")
    monkeypatch.setattr("bookrag_cloud.worker.ingest_document", broken)
    assert work_once(repo, object(), object(), Settings()) is True
    assert repo.expired == 1
    assert "secret" not in repo.failed[2]


def test_worker_reports_password_required_without_retry(monkeypatch):
    doc = uuid4()
    class Repo:
        def flag_stale_pending(self): pass
        def fail_exhausted_jobs(self): pass
        def claim_job(self): return {"document_id": doc, "attempts": 1, "claim_token": uuid4()}
        def job_document(self, doc_id): return {"id": doc_id}
        def job_failure(self, doc_id, token, attempts, message): self.failed = (attempts, message)
    repo = Repo()
    def locked(*args): raise PasswordProtectedPdfError("private exception")
    monkeypatch.setattr("bookrag_cloud.worker.ingest_document", locked)
    assert work_once(repo, object(), object(), Settings()) is True
    assert repo.failed == (3, "This PDF requires a password. Upload an unlocked copy.")
