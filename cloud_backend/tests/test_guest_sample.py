"""The configured sample is readable, but remains owned by its uploader."""
from uuid import uuid4

from bookrag_cloud import main
from bookrag_cloud.main import app
from bookrag_cloud.schemas import Answer, Citation, Timings, Usage
from tests.test_api import FakeRepo, OWNER, OTHER, DOC, client_for


def teardown_function():
    app.dependency_overrides.clear()


class SampleRepo(FakeRepo):
    def __init__(self):
        super().__init__()
        self.retrieval_owners = []
        self.sample_reservations = 0

    def ready_sample_document(self, document_id):
        return self.row if document_id == DOC and self.row["status"] == "ready" else None

    def reserve_question(self, *args, **kwargs):
        if "sample_daily_usd_limit" in kwargs:
            self.sample_reservations += 1
        return super().reserve_question(*args)

    def dense_top(self, owner, doc, vector, limit):
        self.retrieval_owners.append(owner)
        return super().dense_top(owner, doc, vector, limit)

    def passages(self, owner, doc):
        return [dict(row, pdf_page=1, text="The answer is seven. " * 40)
                for row in super().passages(owner, doc)]


def test_shared_sample_is_ready_and_uses_source_passages_but_guest_usage(monkeypatch):
    monkeypatch.setattr(main, "_sample_id", lambda: DOC)
    monkeypatch.setattr(main, "_approved_sample", lambda row: True)
    repo = SampleRepo()
    guest, _, _ = client_for(OTHER, repo)
    listed = guest.get("/api/v1/documents")
    assert listed.status_code == 200
    assert listed.json()["documents"][0]["is_sample"] is True
    viewed = guest.get(f"/api/v1/documents/{DOC}/pdf")
    assert viewed.status_code == 403
    answered = guest.post(f"/api/v1/documents/{DOC}/chat", json={"question": "What is the answer?"})
    assert answered.status_code == 200
    assert repo.retrieval_owners == [OWNER]
    # 004_saved_answers requires (document_id, owner_id) to be the source PDF's
    # owner. Exact cache reuse is therefore shared, while UI history is per guest.
    assert repo.saved[0]["owner_id"] == OWNER
    repeat = guest.post(f"/api/v1/documents/{DOC}/chat", json={"question": "What is the answer?"})
    assert repeat.status_code == 200
    assert repeat.json()["reused_answer"] is True
    assert len(repeat.json()["citations"][0]["excerpt"]) <= 282
    assert repo.retrieval_owners == [OWNER]
    assert repo.sample_reservations == 1
    assert len(answered.json()["citations"][0]["excerpt"]) <= 282
    assert len(repo.saved[0]["citations"][0]["excerpt"]) > 282
    assert answered.json()["citations"][0]["pdf_page"] == 1
    another_guest, _, _ = client_for(uuid4(), repo)
    cross_guest_repeat = another_guest.post(
        f"/api/v1/documents/{DOC}/chat", json={"question": "What is the answer?"}
    )
    assert cross_guest_repeat.status_code == 200
    assert cross_guest_repeat.json()["reused_answer"] is True
    assert repo.retrieval_owners == [OWNER]
    assert guest.delete(f"/api/v1/documents/{DOC}").status_code == 404
    assert repo.row["status"] == "ready"


def test_no_other_private_document_becomes_visible(monkeypatch):
    monkeypatch.setattr(main, "_sample_id", lambda: uuid4())
    monkeypatch.setattr(main, "_approved_sample", lambda row: True)
    repo = SampleRepo()
    guest, _, _ = client_for(OTHER, repo)
    assert guest.get(f"/api/v1/documents/{DOC}").status_code == 404
    assert guest.post(f"/api/v1/documents/{DOC}/chat", json={"question": "What is the answer?"}).status_code == 404
    assert repo.saved == []


def test_mismatched_file_digest_keeps_sample_private(monkeypatch):
    monkeypatch.setattr(main, "_sample_id", lambda: DOC)
    monkeypatch.setattr(main, "_approved_sample", lambda row: False)
    repo = SampleRepo()
    guest, _, _ = client_for(OTHER, repo)
    assert guest.get("/api/v1/documents").json()["documents"] == []
    assert guest.get(f"/api/v1/documents/{DOC}").status_code == 404


def test_multiple_cited_pages_keep_references_without_full_passages():
    citations = [Citation(passage_id=uuid4(), pdf_page=page, excerpt="Relevant source text. " * 80)
                 for page in (7, 11, 23, 40)]
    answer = Answer(answer="The explanation uses four passages.", enough_evidence=True,
                    evidence_status="direct_answer", citations=citations,
                    timings_ms=Timings(search=0, rerank=0, answer=0), usage=Usage())
    guest_view = main._sample_answer_view(answer, "Explain the topic")
    assert [c.pdf_page for c in guest_view.citations] == [7, 11, 23, 40]
    assert all(len(c.excerpt) <= 282 for c in guest_view.citations)
    assert all(len(c.excerpt) > 282 for c in answer.citations)
