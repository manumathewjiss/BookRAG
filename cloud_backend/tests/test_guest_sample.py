"""The configured sample is readable, but remains owned by its uploader."""
import io
from uuid import uuid4

from pypdf import PdfReader

from bookrag_cloud import main
from bookrag_cloud.main import app
from tests.test_api import FakeRepo, OWNER, OTHER, DOC, client_for
from tests.pdf_fixture import two_page_pdf


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
        return [dict(row, pdf_page=1) for row in super().passages(owner, doc)]

    def cited_sample_page(self, source_owner, document_id, passage_id, digest, pipeline_version):
        for saved in self.saved:
            if saved["owner_id"] == source_owner and saved["document_id"] == document_id:
                if any(str(c["passage_id"]) == str(passage_id) for c in saved["citations"]):
                    return 1
        return None


def test_shared_sample_is_ready_and_uses_source_passages_but_guest_usage(monkeypatch):
    monkeypatch.setattr(main, "_sample_id", lambda: DOC)
    monkeypatch.setattr(main, "_approved_sample", lambda row: True)
    repo = SampleRepo()
    guest, _, storage = client_for(OTHER, repo)
    listed = guest.get("/api/v1/documents")
    assert listed.status_code == 200
    assert listed.json()["documents"][0]["is_sample"] is True
    storage.download = lambda path: two_page_pdf("Page one sample.", "Page two stays private.")
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
    assert repo.retrieval_owners == [OWNER]
    assert repo.sample_reservations == 1
    citation_id = repo.saved[0]["citations"][0]["passage_id"]
    cited_page = guest.get(f"/api/v1/documents/{DOC}/citations/{citation_id}/page")
    assert cited_page.status_code == 200
    assert len(PdfReader(io.BytesIO(cited_page.content)).pages) == 1
    assert guest.get(f"/api/v1/documents/{DOC}/citations/{uuid4()}/page").status_code == 404
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
