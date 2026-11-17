import json
from uuid import uuid4

from bookrag_cloud.config import Settings
from bookrag_cloud.providers import HostedModels
from bookrag_cloud.question_preview import sign_preview, verify_preview
from bookrag_cloud.main import app
from tests.test_api import FakeModels, FakeRepo, OWNER, OTHER, DOC, client_for


def test_preview_token_binds_user_document_digest_question_and_language():
    owner, other, document = uuid4(), uuid4(), uuid4()
    token = sign_preview("private-key", owner, document, "digest-1", "njan poyittu varam",
                         "ml", "ഞാൻ പോയിട്ട് വരാം", "I will go and come back")
    assert verify_preview("private-key", token, owner, document, "digest-1",
                          "njan poyittu varam", "ml")["english"] == "I will go and come back"
    assert verify_preview("private-key", token, other, document, "digest-1", "njan poyittu varam", "ml") is None
    assert verify_preview("private-key", token, owner, document, "digest-2", "njan poyittu varam", "ml") is None
    assert verify_preview("private-key", token, owner, document, "digest-1", "njan poyittu varam", "sa") is None
    assert verify_preview("private-key", token, owner, document, "digest-1", "different question", "ml") is None
    assert verify_preview("private-key", token[:-1] + "0", owner, document, "digest-1", "njan poyittu varam", "ml") is None


def test_selected_language_guides_script_and_meaning_preview(monkeypatch):
    import bookrag_cloud.providers as module
    def fake(url, key, body, timeout=60):
        assert url.endswith("/responses")
        assert "Malayalam" in body["instructions"]
        assert "Do not answer" in body["instructions"]
        assert body["store"] is False
        return {"status": "completed", "output": [{"content": [{"type": "output_text", "text": json.dumps({
            "native_script": "ഞാൻ പോയിട്ട് വരാം", "english_meaning": "I will go and come back",
            "needs_clarification": False,
        })}]}], "usage": {"input_tokens": 20, "output_tokens": 15}}
    monkeypatch.setattr(module, "_json_post", fake)
    preview, usage = HostedModels(Settings()).prepare_question("njan poyittu varam", "ml")
    assert preview["native_script"] == "ഞാൻ പോയിട്ട് വരാം"
    assert preview["english_meaning"] == "I will go and come back"
    assert usage["output_tokens"] == 15


def test_preview_requires_ownership_and_chat_uses_confirmed_english(monkeypatch):
    import bookrag_cloud.main as main
    monkeypatch.setattr(main, "settings", lambda: Settings(supabase_service_role_key="private-key"))
    class Repo(FakeRepo):
        def reserve_question_preview(self, *args, **kwargs): return uuid4()
        def settle_question_preview(self, *args, **kwargs): self.counters.append(("preview", args))
    class Models(FakeModels):
        def __init__(self): self.searched = []
        def prepare_question(self, question, language):
            assert question == "njan poyittu varam" and language == "ml"
            return {"native_script": "ഞാൻ പോയിട്ട് വരാം", "english_meaning": "I will go and come back",
                    "needs_clarification": False}, {"input_tokens": 10, "output_tokens": 10}
        def embed(self, texts, mode):
            self.searched.append(texts[0])
            return super().embed(texts, mode)
        def answer(self, question, passages):
            assert "Original question (ml): njan poyittu varam" in question
            assert "Confirmed English meaning: I will go and come back" in question
            return super().answer(question, passages)
    repo, models = Repo(), Models()
    other_client, _, _ = client_for(OTHER, repo=repo, models=models)
    path = f"/api/v1/documents/{DOC}/question-preview"
    request = {"question": "njan poyittu varam", "question_language": "ml"}
    assert other_client.post(path, json=request).status_code == 404
    owner_client, _, _ = client_for(OWNER, repo=repo, models=models)
    response = owner_client.post(path, json=request)
    assert response.status_code == 200
    preview = response.json()
    assert preview["native_script"] == "ഞാൻ പോയിട്ട് വരാം"
    chat_path = f"/api/v1/documents/{DOC}/chat"
    payload = {**request, "answer_language": "en", "preview_token": preview["preview_token"]}
    assert owner_client.post(chat_path, json={**payload, "question": "changed text"}).status_code == 400
    answer = owner_client.post(chat_path, json=payload)
    assert answer.status_code == 200
    assert models.searched == ["I will go and come back"]
    assert any(event[0] == "preview" for event in repo.counters)
    app.dependency_overrides.clear()
