import pytest

from bookrag_cloud.verification_guard import GuardedModels, VerificationLimitReached
from scripts.cloud_smoke import approval_ok, fixture


class FakeModels:
    def __init__(self):
        self.calls = []

    def embed(self, texts, mode):
        self.calls.append(("embed", mode))
        return [[0.0] * 1024 for _ in texts], 5

    def rerank(self, question, passages):
        self.calls.append(("rerank", question))
        return passages, 5

    def answer(self, question, passages):
        self.calls.append(("answer", question))
        return {"answer": "ok"}, {"input_tokens": 5, "output_tokens": 1}


def test_all_requests_reserved_before_dispatch():
    fake = FakeModels()
    guarded = GuardedModels(fake, max_voyage_requests=1, max_openai_requests=1)
    guarded.embed(["some text"], "document")
    with pytest.raises(VerificationLimitReached):
        guarded.embed(["retry"], "document")
    guarded.answer("some question", [])
    with pytest.raises(VerificationLimitReached):
        guarded.answer("retry", [])
    assert len(fake.calls) == 2


def test_cost_caps_block_before_dispatch():
    fake = FakeModels()
    guarded = GuardedModels(fake, max_voyage_usd=0, max_openai_usd=0)
    with pytest.raises(VerificationLimitReached):
        guarded.embed(["text"], "query")
    with pytest.raises(VerificationLimitReached):
        guarded.answer("question", [])
    assert fake.calls == []


def test_pdf_page_map_and_exact_approval(tmp_path):
    _, manifest = fixture()
    approval = tmp_path / "approval.json"
    assert not approval_ok(approval, manifest)
    approval.write_text('{"approved":true}')
    assert not approval_ok(approval, manifest)
    import json
    approval.write_text(json.dumps({"approved": True, "pdf_sha256": manifest["sha256"],
                                    "max_voyage_requests": 5, "max_openai_requests": 2,
                                    "max_voyage_usd": 0.02, "max_openai_usd": 0.10}))
    assert approval_ok(approval, manifest)
    assert manifest["pages"] == 2 and manifest["passages"] == 2
