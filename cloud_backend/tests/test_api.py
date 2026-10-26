from datetime import datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient

from bookrag_cloud.main import app, get_models, get_repo, get_storage
from bookrag_cloud.security import verify_access_token

OWNER = uuid4()
OTHER = uuid4()
DOC = uuid4()


class FakeRepo:
    def __init__(self):
        self.row = {"id": DOC, "owner_id": OWNER, "title": "My book", "filename": "book.pdf",
                    "status": "ready", "page_count": 1, "passage_count": 1, "error": None,
                    "storage_path": f"{OWNER}/{DOC}/source.pdf",
                    "created_at": datetime.now(timezone.utc), "updated_at": datetime.now(timezone.utc)}
        self.counters = []

    def count_today(self, owner, op):
        return 0

    def document(self, owner, doc):
        return self.row if owner == OWNER and doc == DOC else None

    def list_documents(self, owner):
        return [self.row] if owner == OWNER else []

    def reserve_question(self, owner, doc, limit, daily_usd_limit, reserve_usd, minute_limit):
        return uuid4()

    def settle_question(self, *args):
        self.counters.append(args)

    def dense_top(self, owner, doc, vector, limit):
        return self.passages(owner, doc)

    def passages(self, owner, doc):
        return [{"id": uuid4(), "chunk_index": 0, "pdf_page": 7, "text": "The answer is seven."}]

    def record_usage(self, *args):
        self.counters.append(args)

    def delete_document(self, owner, doc):
        return {"storage_path": self.row["storage_path"]}

    def create_document(self, owner, document_id, title, filename, path, digest, daily_limit):
        return {**self.row, "id": document_id, "owner_id": owner, "title": title,
                "filename": filename, "storage_path": path, "status": "queued"}


class FakeStorage:
    def __init__(self): self.deleted = []
    def delete(self, path): self.deleted.append(path)
    def upload(self, path, data): self.uploaded = (path, data)


class FakeModels:
    def embed(self, text, mode): return [[0.0] * 1024], 10
    def rerank(self, question, passages): return passages, 5
    def answer(self, question, passages):
        return ({"answer": "The answer is seven.", "enough_evidence": True,
                 "event_match": "direct_answer", "supporting_passage_ids": [str(passages[0]["id"])]},
                {"input_tokens": 20, "output_tokens": 5})


def client_for(owner, repo=None, models=None):
    repo = repo or FakeRepo()
    storage = FakeStorage()
    app.dependency_overrides[verify_access_token] = lambda: owner
    app.dependency_overrides[get_repo] = lambda: repo
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[get_models] = lambda: models or FakeModels()
    return TestClient(app), repo, storage


def teardown_function():
    app.dependency_overrides.clear()


def test_cors_allows_configured_local_origin_only():
    client = TestClient(app)
    allowed = client.options(
        "/api/v1/documents",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST"},
    )
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:3000"
    blocked = client.options(
        "/api/v1/documents",
        headers={"Origin": "https://unlisted.example", "Access-Control-Request-Method": "POST"},
    )
    assert blocked.status_code == 400
    assert "access-control-allow-origin" not in blocked.headers


def test_other_user_cannot_read_delete_or_chat():
    client, repo, storage = client_for(OTHER)
    assert client.get(f"/api/v1/documents/{DOC}").status_code == 404
    assert client.delete(f"/api/v1/documents/{DOC}").status_code == 404
    assert client.post(f"/api/v1/documents/{DOC}/chat", json={"question": "What happened?"}).status_code == 404
    assert storage.deleted == []


def test_direct_answer_cites_only_saved_page():
    client, repo, _ = client_for(OWNER)
    response = client.post(f"/api/v1/documents/{DOC}/chat", json={"question": "What happened?"})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["enough_evidence"] is True and data["citations"][0]["pdf_page"] == 7


def test_document_wide_absence_has_no_misleading_citation():
    class Refuse(FakeModels):
        def answer(self, question, passages):
            return {"answer": "No evidence", "enough_evidence": False,
                    "event_match": "absent", "supporting_passage_ids": [str(passages[0]["id"])]}, {}
    client, _, _ = client_for(OWNER, models=Refuse())
    data = client.post(f"/api/v1/documents/{DOC}/chat", json={"question": "What is the author's email?"}).json()
    assert data["enough_evidence"] is False and data["citations"] == []


def test_invalid_model_citation_withholds_answer():
    class WrongId(FakeModels):
        def answer(self, question, passages):
            return {"answer": "Seven", "enough_evidence": True,
                    "event_match": "direct_answer", "supporting_passage_ids": [str(uuid4())]}, {}
    client, _, _ = client_for(OWNER, models=WrongId())
    data = client.post(f"/api/v1/documents/{DOC}/chat", json={"question": "What happened?"}).json()
    assert data["enough_evidence"] is False
    assert data["evidence_status"] == "unverified" and data["citations"] == []


def test_upload_rejects_non_pdf_before_storage():
    client, _, storage = client_for(OWNER)
    response = client.post("/api/v1/documents", files={"file": ("a.txt", b"hello", "text/plain")})
    assert response.status_code == 400 and not hasattr(storage, "uploaded")


def test_upload_queues_pdf_with_server_generated_owner_path():
    client, _, storage = client_for(OWNER)
    response = client.post("/api/v1/documents", files={"file": ("a.pdf", b"%PDF-1.7\n", "application/pdf")})
    assert response.status_code == 202, response.text
    assert response.json()["document"]["status"] == "queued"
    assert storage.uploaded[0].startswith(str(OWNER) + "/")


def test_atomic_upload_limit_cleans_storage_object():
    from bookrag_cloud.repository import UsageLimitReached
    class Full(FakeRepo):
        def create_document(self, *args):
            raise UsageLimitReached("Limit reached after concurrent upload")
    client, _, storage = client_for(OWNER, repo=Full())
    response = client.post("/api/v1/documents", files={"file": ("a.pdf", b"%PDF-1.7\n", "application/pdf")})
    assert response.status_code == 429
    assert storage.deleted == [storage.uploaded[0]]
