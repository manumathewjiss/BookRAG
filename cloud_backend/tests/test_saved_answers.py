"""Saved-answer reuse: exact canonical repeat, isolation, invalidation, no provider calls on hit."""
from datetime import datetime, timezone
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
import time
from uuid import uuid4

import psycopg
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from bookrag_cloud.main import app, chat, delete_document, get_models, get_repo, get_storage
from bookrag_cloud.question_match import ANSWER_PIPELINE_VERSION, canonicalize_question, question_signature
from bookrag_cloud.security import verify_access_token
from bookrag_cloud.schemas import ChatRequest

OWNER = uuid4()
OTHER = uuid4()
DOC = uuid4()
OTHER_DOC = uuid4()
PASSAGE = uuid4()
DIGEST = "abc123digest"


class TrackingModels:
    def __init__(self):
        self.embed_calls = 0
        self.rerank_calls = 0
        self.answer_calls = 0
        self.answer_text = "Neil Armstrong was the first person to walk on the Moon."

    def embed(self, text, mode):
        self.embed_calls += 1
        return [[0.0] * 1024], 10

    def rerank(self, question, passages):
        self.rerank_calls += 1
        return passages, 5

    def answer(self, question, passages):
        self.answer_calls += 1
        return (
            {
                "answer": self.answer_text,
                "enough_evidence": True,
                "event_match": "direct_answer",
                "supporting_passage_ids": [str(passages[0]["id"])],
            },
            {"input_tokens": 20, "output_tokens": 5},
        )


class MemorySavedRepo:
    def __init__(self):
        now = datetime.now(timezone.utc)
        self.docs = {
            DOC: {
                "id": DOC, "owner_id": OWNER, "title": "Apollo", "filename": "apollo.pdf",
                "status": "ready", "page_count": 1, "passage_count": 1, "error": None,
                "storage_path": f"{OWNER}/{DOC}/source.pdf", "sha256": DIGEST,
                "created_at": now, "updated_at": now,
            },
            OTHER_DOC: {
                "id": OTHER_DOC, "owner_id": OWNER, "title": "Other", "filename": "other.pdf",
                "status": "ready", "page_count": 1, "passage_count": 1, "error": None,
                "storage_path": f"{OWNER}/{OTHER_DOC}/source.pdf", "sha256": "otherdigest",
                "created_at": now, "updated_at": now,
            },
        }
        self.saved = []
        self.settled = []
        self.reused_settled = []
        self._answer_lock = Lock()

    @contextmanager
    def answer_lock(self, owner, doc):
        with self._answer_lock:
            yield

    def delete_saved_answers(self, owner, doc):
        self.saved = [s for s in self.saved if not (s["owner_id"] == owner and s["document_id"] == doc)]

    def count_today(self, owner, op):
        return 0

    def document(self, owner, doc):
        row = self.docs.get(doc)
        return row if row and row["owner_id"] == owner and row["status"] != "deleted" else None

    def list_documents(self, owner):
        return [r for r in self.docs.values() if r["owner_id"] == owner and r["status"] != "deleted"]

    def delete_document(self, owner, doc):
        row = self.document(owner, doc)
        if not row:
            return None
        row["status"] = "deleted"
        return {"storage_path": row["storage_path"]}

    def reserve_question(self, owner, doc, limit, daily_usd_limit, reserve_usd, minute_limit):
        return uuid4()

    def settle_question(self, *args, **kwargs):
        self.settled.append((args, kwargs))

    def settle_reused_question(self, owner, event_id):
        self.reused_settled.append((owner, event_id))

    def passages(self, owner, doc):
        if not self.document(owner, doc):
            return []
        return [{"id": PASSAGE, "chunk_index": 0, "pdf_page": 3,
                 "text": "Neil Armstrong was the first person to walk on the Moon."}]

    def dense_top(self, owner, doc, vector, limit):
        return self.passages(owner, doc)

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
            "id": uuid4(),
            "owner_id": owner,
            "document_id": document_id,
            "question_original": question_original,
            "question_canonical": question_canonical,
            "question_signature": question_signature,
            "answer_text": answer_text,
            "enough_evidence": enough_evidence,
            "evidence_status": evidence_status,
            "citations": citations,
            "document_sha256": document_sha256,
            "pipeline_version": pipeline_version,
            "created_at": datetime.now(timezone.utc),
        }
        self.saved.append(row)
        return row


class FakeStorage:
    def __init__(self):
        self.deleted = []

    def delete(self, path):
        self.deleted.append(path)


def _client(owner, repo, models):
    app.dependency_overrides[verify_access_token] = lambda: owner
    app.dependency_overrides[get_repo] = lambda: repo
    app.dependency_overrides[get_storage] = lambda: FakeStorage()
    app.dependency_overrides[get_models] = lambda: models
    return TestClient(app)


def teardown_function():
    app.dependency_overrides.clear()


def test_exact_repeat_returns_stored_answer_without_provider_calls():
    repo, models = MemorySavedRepo(), TrackingModels()
    client = _client(OWNER, repo, models)
    first = client.post(f"/api/v1/documents/{DOC}/chat", json={"question": "Who is Neil Armstrong?"})
    assert first.status_code == 200, first.text
    assert first.json()["reused_answer"] is False
    assert models.answer_calls == 1
    stored_answer = first.json()["answer"]
    stored_citations = first.json()["citations"]

    second = client.post(f"/api/v1/documents/{DOC}/chat", json={"question": "Who is Neil Armstrong?"})
    assert second.status_code == 200
    body = second.json()
    assert body["reused_answer"] is True
    assert body["answer"] == stored_answer
    assert body["citations"] == stored_citations
    assert body["usage"] == {"input_tokens": 0, "output_tokens": 0, "estimated_usd": 0.0}
    assert models.embed_calls == 1 and models.rerank_calls == 1 and models.answer_calls == 1
    assert len(repo.reused_settled) == 1


def test_whitespace_and_question_mark_reuse_without_provider_calls():
    repo, models = MemorySavedRepo(), TrackingModels()
    client = _client(OWNER, repo, models)
    first = client.post(f"/api/v1/documents/{DOC}/chat", json={"question": "Who is Neil Armstrong?"})
    assert first.status_code == 200
    second = client.post(f"/api/v1/documents/{DOC}/chat", json={"question": "  Who   is Neil Armstrong ?  "})
    assert second.status_code == 200
    assert second.json()["reused_answer"] is True
    assert second.json()["answer"] == first.json()["answer"]
    assert second.json()["citations"] == first.json()["citations"]
    assert models.embed_calls == 1 and models.answer_calls == 1


def test_meaningful_rephrase_runs_full_rag():
    repo, models = MemorySavedRepo(), TrackingModels()
    client = _client(OWNER, repo, models)
    assert client.post(f"/api/v1/documents/{DOC}/chat", json={"question": "Who is Neil Armstrong?"}).status_code == 200
    for rephrase in ("Who was Neil Armstrong?", "Who is Neil Armstrong really?",
                     "Who Neil Armstrong really was?"):
        models.answer_text = f"Fresh answer for {rephrase}"
        second = client.post(f"/api/v1/documents/{DOC}/chat", json={"question": rephrase})
        assert second.status_code == 200, rephrase
        assert second.json()["reused_answer"] is False, rephrase
        assert second.json()["answer"] == models.answer_text
    assert models.answer_calls == 4


def test_same_subject_different_question_generates_new_answer():
    repo, models = MemorySavedRepo(), TrackingModels()
    client = _client(OWNER, repo, models)
    assert client.post(f"/api/v1/documents/{DOC}/chat", json={"question": "Who is Neil Armstrong?"}).status_code == 200
    models.answer_text = "He commanded Apollo 11 and walked on the Moon."
    second = client.post(
        f"/api/v1/documents/{DOC}/chat",
        json={"question": "What did Neil Armstrong do at NASA?"},
    )
    assert second.status_code == 200
    assert second.json()["reused_answer"] is False
    assert models.answer_calls == 2


def test_when_question_does_not_reuse_identity_answer():
    repo, models = MemorySavedRepo(), TrackingModels()
    client = _client(OWNER, repo, models)
    assert client.post(f"/api/v1/documents/{DOC}/chat", json={"question": "Who is Neil Armstrong?"}).status_code == 200
    models.answer_text = "He walked on the Moon in 1969."
    second = client.post(
        f"/api/v1/documents/{DOC}/chat",
        json={"question": "When did Neil Armstrong walk on the Moon?"},
    )
    assert second.json()["reused_answer"] is False
    assert models.answer_calls == 2


def test_different_subject_generates_new_answer():
    repo, models = MemorySavedRepo(), TrackingModels()
    client = _client(OWNER, repo, models)
    assert client.post(f"/api/v1/documents/{DOC}/chat", json={"question": "Who is Neil Armstrong?"}).status_code == 200
    models.answer_text = "NASA is the US space agency."
    second = client.post(f"/api/v1/documents/{DOC}/chat", json={"question": "Who is NASA?"})
    assert second.json()["reused_answer"] is False
    assert models.answer_calls == 2


def test_different_user_does_not_reuse():
    repo, models = MemorySavedRepo(), TrackingModels()
    client_a = _client(OWNER, repo, models)
    assert client_a.post(f"/api/v1/documents/{DOC}/chat", json={"question": "Who is Neil Armstrong?"}).status_code == 200
    client_b = _client(OTHER, repo, models)
    assert client_b.post(f"/api/v1/documents/{DOC}/chat", json={"question": "Who is Neil Armstrong?"}).status_code == 404
    assert models.answer_calls == 1


def test_different_pdf_does_not_reuse():
    repo, models = MemorySavedRepo(), TrackingModels()
    client = _client(OWNER, repo, models)
    assert client.post(f"/api/v1/documents/{DOC}/chat", json={"question": "Who is Neil Armstrong?"}).status_code == 200
    second = client.post(f"/api/v1/documents/{OTHER_DOC}/chat", json={"question": "Who is Neil Armstrong?"})
    assert second.status_code == 200
    assert second.json()["reused_answer"] is False
    assert models.answer_calls == 2


def test_deleted_document_removes_saved_answers():
    repo, models = MemorySavedRepo(), TrackingModels()
    client = _client(OWNER, repo, models)
    assert client.post(f"/api/v1/documents/{DOC}/chat", json={"question": "Who is Neil Armstrong?"}).status_code == 200
    assert repo.saved
    assert client.delete(f"/api/v1/documents/{DOC}").status_code == 204
    assert repo.saved == []
    assert client.post(f"/api/v1/documents/{DOC}/chat", json={"question": "Who is Neil Armstrong?"}).status_code == 404


def test_changed_document_digest_does_not_reuse():
    repo, models = MemorySavedRepo(), TrackingModels()
    client = _client(OWNER, repo, models)
    assert client.post(f"/api/v1/documents/{DOC}/chat", json={"question": "Who is Neil Armstrong?"}).status_code == 200
    assert models.answer_calls == 1
    repo.docs[DOC]["sha256"] = "changed-digest"
    second = client.post(f"/api/v1/documents/{DOC}/chat", json={"question": "Who is Neil Armstrong?"})
    assert second.status_code == 200
    assert second.json()["reused_answer"] is False
    assert models.answer_calls == 2


def test_concurrent_identical_saves_keep_first_answer():
    repo = MemorySavedRepo()
    sig = question_signature("Who is Neil Armstrong?")
    first = repo.save_answer(
        OWNER, DOC, "Who is Neil Armstrong?", sig["canonical"], sig,
        "First stored answer", True, "direct_answer",
        [{"passage_id": str(PASSAGE), "pdf_page": 3, "excerpt": "x"}],
        DIGEST, ANSWER_PIPELINE_VERSION,
    )
    second = repo.save_answer(
        OWNER, DOC, "Who is Neil Armstrong?", canonicalize_question("Who is Neil Armstrong?"), sig,
        "Conflicting later answer", True, "direct_answer",
        [{"passage_id": str(PASSAGE), "pdf_page": 9, "excerpt": "y"}],
        DIGEST, ANSWER_PIPELINE_VERSION,
    )
    assert second["answer_text"] == first["answer_text"] == "First stored answer"
    assert len(repo.saved) == 1


def test_simultaneous_identical_requests_use_one_paid_pipeline():
    second_question = "  Who is Neil Armstrong ?  "
    repo = MemorySavedRepo()

    class SlowModels(TrackingModels):
        def answer(self, question, passages):
            time.sleep(0.08)
            return super().answer(question, passages)

    models = SlowModels()
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(chat, DOC, ChatRequest(question="Who is Neil Armstrong?"), OWNER, repo, models)
        time.sleep(0.02)
        second = pool.submit(chat, DOC, ChatRequest(question=second_question), OWNER, repo, models)
        a, b = first.result(), second.result()
    assert a.reused_answer is False
    assert b.reused_answer is True
    assert a.answer == b.answer and a.citations == b.citations
    assert b.usage.estimated_usd == 0
    assert (models.embed_calls, models.rerank_calls, models.answer_calls) == (1, 1, 1)
    assert len(repo.saved) == 1


def test_cache_write_failure_returns_generated_answer_and_settles_usage():
    class FailingCacheRepo(MemorySavedRepo):
        def save_answer(self, *args, **kwargs):
            assert self.settled, "paid usage must be settled before the optional cache write"
            raise psycopg.OperationalError("cache unavailable")

    repo, models = FailingCacheRepo(), TrackingModels()
    answer = chat(DOC, ChatRequest(question="Who is Neil Armstrong?"), OWNER, repo, models)
    assert answer.answer == models.answer_text
    assert answer.reused_answer is False
    assert answer.citations[0].pdf_page == 3
    assert len(repo.settled) == 1
    assert models.answer_calls == 1


def test_cache_purge_failure_keeps_pdf_and_document():
    class FailingPurgeRepo(MemorySavedRepo):
        def delete_saved_answers(self, owner, doc):
            raise psycopg.OperationalError("cache unavailable")

    repo, storage = FailingPurgeRepo(), FakeStorage()
    with pytest.raises(psycopg.OperationalError):
        delete_document(DOC, OWNER, repo, storage)
    assert storage.deleted == []
    assert repo.document(OWNER, DOC) is not None


def test_cross_user_requests_do_not_touch_cache_or_paid_models():
    repo, models, storage = MemorySavedRepo(), TrackingModels(), FakeStorage()
    before = list(repo.saved)
    with pytest.raises(HTTPException) as question_error:
        chat(DOC, ChatRequest(question="Who is Neil Armstrong?"), OTHER, repo, models)
    with pytest.raises(HTTPException) as delete_error:
        delete_document(DOC, OTHER, repo, storage)
    assert question_error.value.status_code == delete_error.value.status_code == 404
    assert (models.embed_calls, models.rerank_calls, models.answer_calls) == (0, 0, 0)
    assert repo.saved == before and storage.deleted == []
