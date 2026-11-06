"""Offline API + worker exercise with mocked Supabase Auth/Storage and hosted AI."""
import hashlib
import json
import re
from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from bookrag_cloud.config import Settings
from bookrag_cloud.main import app, get_models, get_repo, get_storage
from bookrag_cloud.providers import HostedModels
from bookrag_cloud.repository import UncertainEmbeddingBatch
from bookrag_cloud.storage import PrivateStorage
from bookrag_cloud.worker import work_once
from tests.pdf_fixture import two_page_pdf


class MemoryRepository:
    def __init__(self):
        self.docs = {}
        self.rows = {}
        self.jobs = {}
        self.batches = {}
        self.usages = []
        self.questions = 0
        self.saved = []

    @contextmanager
    def answer_lock(self, owner, doc):
        yield

    def delete_saved_answers(self, owner, doc):
        self.saved = [item for item in self.saved if item["owner_id"] != owner or item["document_id"] != doc]

    def count_today(self, owner, operation):
        if operation == "upload":
            return sum(row["owner_id"] == owner for row in self.docs.values())
        return self.questions

    def create_document(self, owner, doc, title, filename, path, digest, daily_limit):
        now = datetime.now(timezone.utc)
        row = {"id": doc, "owner_id": owner, "title": title, "filename": filename,
               "storage_path": path, "sha256": digest, "status": "queued", "page_count": 0,
               "passage_count": 0, "error": None, "created_at": now, "updated_at": now}
        self.docs[doc] = row
        self.jobs[doc] = {"document_id": doc, "status": "queued", "attempts": 0}
        return row

    def list_documents(self, owner):
        return [row for row in self.docs.values() if row["owner_id"] == owner and row["status"] != "deleted"]

    def document(self, owner, doc):
        row = self.docs.get(doc)
        return row if row and row["owner_id"] == owner and row["status"] != "deleted" else None

    def delete_document(self, owner, doc):
        row = self.document(owner, doc)
        if row:
            row["status"] = "deleted"
            self.rows.pop(doc, None)
            self.jobs.pop(doc, None)
            return {"storage_path": row["storage_path"]}
        return None

    def list_saved_answers(self, owner, document_id, document_sha256, pipeline_version):
        return [
            row for row in self.saved
            if row["owner_id"] == owner and row["document_id"] == document_id
            and row["document_sha256"] == document_sha256
            and row["pipeline_version"] == pipeline_version
        ]

    def find_exact_saved_answer(self, owner, document_id, question_canonical, document_sha256, pipeline_version):
        for row in self.list_saved_answers(owner, document_id, document_sha256, pipeline_version):
            if row["question_canonical"] == question_canonical:
                return row
        return None

    def save_answer(self, owner, document_id, question_original, question_canonical, question_signature,
                    answer_text, enough_evidence, evidence_status, citations, document_sha256, pipeline_version):
        existing = self.find_exact_saved_answer(
            owner, document_id, question_canonical, document_sha256, pipeline_version
        )
        if existing:
            return existing
        row = {
            "id": uuid4(), "owner_id": owner, "document_id": document_id,
            "question_original": question_original, "question_canonical": question_canonical,
            "question_signature": question_signature, "answer_text": answer_text,
            "enough_evidence": enough_evidence, "evidence_status": evidence_status,
            "citations": citations,             "document_sha256": document_sha256,
            "pipeline_version": pipeline_version,
        }
        self.saved.append(row)
        return row

    def settle_reused_question(self, owner, event_id):
        self.usages.append((owner, event_id, "reuse"))

    def flag_stale_pending(self): pass
    def fail_exhausted_jobs(self): pass

    def claim_job(self):
        for job in self.jobs.values():
            if job["status"] == "queued":
                job.update(status="running", attempts=job["attempts"] + 1, claim_token=uuid4())
                return job.copy()
        return None

    def job_document(self, doc):
        row = self.docs.get(doc)
        return row if row and row["status"] != "deleted" else None

    def mark_processing(self, doc, token):
        assert self.jobs[doc]["claim_token"] == token
        self.docs[doc]["status"] = "processing"

    def renew_job_lease(self, doc, token):
        assert self.jobs[doc]["claim_token"] == token

    def begin_embedding_batch(self, doc, token, index, digest):
        row = self.batches.get((doc, index))
        if row:
            if row["digest"] != digest or row["status"] == "pending":
                raise UncertainEmbeddingBatch("Unknown or changed batch")
            return row["vectors"]
        self.batches[(doc, index)] = {"digest": digest, "status": "pending", "vectors": None}
        return None

    def complete_embedding_batch(self, owner, doc, token, index, digest, vectors, tokens):
        row = self.batches[(doc, index)]
        assert row["status"] == "pending" and row["digest"] == digest
        row.update(status="complete", vectors=vectors)
        self.usages.append((owner, "embedding", tokens))

    def release_rejected_batch(self, doc, token, index): self.batches.pop((doc, index), None)
    def has_pending_batch(self, doc): return any(k[0] == doc and row["status"] == "pending" for k, row in self.batches.items())
    def flag_uncertain_job(self, doc, token):
        self.jobs[doc]["status"] = "attention"
        self.docs[doc]["status"] = "failed"
    def clear_reviewed_batch(self, doc, index):
        if self.jobs[doc]["status"] != "attention" or self.batches[(doc, index)]["status"] != "pending":
            return False
        self.batches.pop((doc, index))
        self.jobs[doc]["status"] = "queued"
        self.docs[doc]["status"] = "queued"
        return True
    def job_failure(self, doc, token, attempts, message):
        new_status = "failed" if attempts >= 3 else "queued"
        self.jobs[doc]["status"] = new_status
        self.docs[doc]["status"] = new_status

    def store_passages(self, owner, doc, token, rows, page_count, expected_batches):
        assert self.jobs[doc]["claim_token"] == token
        assert sum(k[0] == doc and value["status"] == "complete" for k, value in self.batches.items()) == expected_batches
        self.rows[doc] = [{**row, "id": uuid4()} for row in rows]
        self.docs[doc].update(status="ready", page_count=page_count, passage_count=len(rows))
        self.jobs[doc]["status"] = "done"
        return True

    def passages(self, owner, doc):
        return [{k: row[k] for k in ("id", "chunk_index", "pdf_page", "text")}
                for row in self.rows.get(doc, [])] if self.document(owner, doc) else []

    def dense_top(self, owner, doc, vector, limit):
        rows = self.rows.get(doc, []) if self.document(owner, doc) else []
        ordered = sorted(rows, key=lambda row: -sum(x * y for x, y in zip(row["embedding"], vector)))
        return [{k: row[k] for k in ("id", "chunk_index", "pdf_page", "text")} for row in ordered[:limit]]

    def reserve_question(self, owner, doc, daily, usd, reserve, minute):
        self.questions += 1
        return uuid4()

    def settle_question(self, *args, **kwargs): self.usages.append((args, kwargs))


class MockResponse:
    def __init__(self, data=None, content=b"", status=200):
        self.data, self.content, self.status_code = data, content, status
    def json(self): return self.data
    def raise_for_status(self):
        if self.status_code >= 400: raise RuntimeError("mock HTTP failure")


def test_mocked_upload_worker_chat_delete_and_two_user_isolation(monkeypatch):
    import httpx
    import bookrag_cloud.main as main
    import bookrag_cloud.security as security

    owner_a, owner_b = uuid4(), uuid4()
    cfg = Settings(supabase_url="https://project.supabase.co", supabase_service_role_key="mock-service",
                   voyage_api_key="mock-voyage", openai_api_key="mock-openai")
    repo = MemoryRepository()
    storage = PrivateStorage(cfg)
    models = HostedModels(cfg)
    objects = {}
    calls = {"embed": 0, "rerank": 0, "sol": 0}

    def fake_get(url, headers, timeout):
        if url.endswith("/auth/v1/user"):
            token = headers["Authorization"]
            if token == "Bearer user-a": return MockResponse({"id": str(owner_a)})
            if token == "Bearer user-b": return MockResponse({"id": str(owner_b)})
            return MockResponse(status=401)
        assert "/object/authenticated/" in url
        return MockResponse(content=objects[url.replace("/object/authenticated/", "/object/")])

    def fake_post(url, headers, timeout, **kwargs):
        if "/storage/v1/object/" in url:
            objects[url] = kwargs["content"]
            return MockResponse({"Key": url})
        body = kwargs["json"]
        if url.endswith("/embeddings"):
            calls["embed"] += 1
            vectors = []
            for i, text in enumerate(body["input"]):
                blue = body["input_type"] == "query" or "cobalt blue" in text
                vectors.append({"index": i, "embedding": ([0.0, 1.0] if blue else [1.0, 0.0]) + [0.0] * 1022})
            return MockResponse({"data": vectors, "usage": {"total_tokens": 30}})
        if url.endswith("/rerank"):
            calls["rerank"] += 1
            indexes = sorted(range(len(body["documents"])), key=lambda i: "cobalt blue" not in body["documents"][i])
            return MockResponse({"data": [{"index": i} for i in indexes], "usage": {"total_tokens": 40}})
        assert url.endswith("/responses")
        calls["sol"] += 1
        match = re.search(r"passage_id=([0-9a-f-]+); PDF page=2", body["input"])
        assert match
        answer = {"answer": "The second page says cobalt blue.", "supporting_passage_ids": [match.group(1)],
                  "enough_evidence": True, "event_match": "direct_answer"}
        return MockResponse({"status": "completed", "output": [{"content": [{"type": "output_text", "text": json.dumps(answer)}]}],
                             "usage": {"input_tokens": 100, "output_tokens": 20}})

    def fake_delete(url, headers, timeout):
        objects.pop(url, None)
        return MockResponse({"message": "Deleted"})

    monkeypatch.setattr(httpx, "get", fake_get)
    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(httpx, "delete", fake_delete)
    monkeypatch.setattr(main, "settings", lambda: cfg)
    monkeypatch.setattr(security, "settings", lambda: cfg)
    app.dependency_overrides[get_repo] = lambda: repo
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[get_models] = lambda: models
    try:
        client = TestClient(app)
        auth_a, auth_b = {"Authorization": "Bearer user-a"}, {"Authorization": "Bearer user-b"}
        pdf = two_page_pdf("First page says copper.", "Second page says cobalt blue.")
        uploaded = client.post("/api/v1/documents", headers=auth_a,
                               files={"file": ("colors.pdf", pdf, "application/pdf")})
        assert uploaded.status_code == 202, uploaded.text
        doc = UUID(uploaded.json()["document"]["id"])
        assert client.get(f"/api/v1/documents/{doc}", headers=auth_b).status_code == 404
        assert client.get(f"/api/v1/documents/{doc}/pdf", headers=auth_b).status_code == 404
        assert client.get(f"/api/v1/documents/{doc}/pdf").status_code == 401
        pdf_reply = client.get(f"/api/v1/documents/{doc}/pdf", headers=auth_a)
        assert pdf_reply.status_code == 200 and pdf_reply.content == pdf
        assert pdf_reply.headers["cache-control"] == "private, no-store"
        assert pdf_reply.headers["content-type"] == "application/pdf"
        assert client.get("/api/v1/documents", headers=auth_b).json()["documents"] == []
        assert client.post(f"/api/v1/documents/{doc}/chat", headers=auth_a,
                           json={"question": "What color is on the second page?"}).status_code == 409
        assert work_once(repo, storage, models, cfg) is True
        assert client.get(f"/api/v1/documents/{doc}", headers=auth_a).json()["document"]["status"] == "ready"
        answer = client.post(f"/api/v1/documents/{doc}/chat", headers=auth_a,
                             json={"question": "What color is on the second page?"})
        assert answer.status_code == 200, answer.text
        assert answer.json()["citations"][0]["pdf_page"] == 2
        assert "cobalt blue" in answer.json()["citations"][0]["excerpt"]
        assert answer.json()["reused_answer"] is False
        reused = client.post(f"/api/v1/documents/{doc}/chat", headers=auth_a,
                             json={"question": "What color is on the second page?"})
        assert reused.status_code == 200
        assert reused.json()["reused_answer"] is True
        assert reused.json()["answer"] == answer.json()["answer"]
        assert reused.json()["citations"] == answer.json()["citations"]
        assert calls == {"embed": 2, "rerank": 1, "sol": 1}
        assert client.post(f"/api/v1/documents/{doc}/chat", headers=auth_b,
                           json={"question": "What is on the second page?"}).status_code == 404
        assert client.delete(f"/api/v1/documents/{doc}", headers=auth_b).status_code == 404
        assert client.delete(f"/api/v1/documents/{doc}", headers=auth_a).status_code == 204
        assert objects == {} and repo.rows.get(doc) is None and repo.saved == []
        assert client.get(f"/api/v1/documents/{doc}", headers=auth_a).status_code == 404
        assert client.get(f"/api/v1/documents/{doc}/pdf", headers=auth_a).status_code == 404
        assert client.get("/api/v1/me", headers={"Authorization": "Bearer bad"}).status_code == 401
    finally:
        app.dependency_overrides.clear()
