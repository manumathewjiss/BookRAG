"""A changed question runs retrieval. Strict v1 does not call a verifier."""
from fastapi.testclient import TestClient

from bookrag_cloud.main import app, get_models, get_repo, get_storage
from bookrag_cloud.security import verify_access_token

from .test_saved_answers import DOC, FakeStorage, MemorySavedRepo, OWNER, TrackingModels, teardown_function  # noqa: F401


def test_paraphrase_runs_retrieval_and_makes_no_verifier_call():
    repo, models = MemorySavedRepo(), TrackingModels()
    app.dependency_overrides[verify_access_token] = lambda: OWNER
    app.dependency_overrides[get_repo] = lambda: repo
    app.dependency_overrides[get_storage] = lambda: FakeStorage()
    app.dependency_overrides[get_models] = lambda: models
    client = TestClient(app)
    first = client.post(
        f"/api/v1/documents/{DOC}/chat",
        json={"question": "Who was the first person to walk on the Moon?"},
    )
    assert first.status_code == 200
    models.answer_text = "Buzz Aldrin was the second person."
    second = client.post(
        f"/api/v1/documents/{DOC}/chat",
        json={"question": "Who first stepped onto the lunar surface?"},
    )
    third = client.post(
        f"/api/v1/documents/{DOC}/chat",
        json={"question": "Who was the second person to walk on the Moon?"},
    )
    assert second.json()["reused_answer"] is False
    assert third.json()["reused_answer"] is False
    assert third.json()["answer"] == models.answer_text
    assert not hasattr(models, "verify_question_equivalence")
    assert models.answer_calls == 3
    assert models.embed_calls == 3
