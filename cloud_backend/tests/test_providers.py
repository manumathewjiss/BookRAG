from uuid import uuid4

import pytest

from bookrag_cloud.config import Settings
from bookrag_cloud.providers import HostedModels, ProviderError


def test_voyage_embedding_format_and_order(monkeypatch):
    import bookrag_cloud.providers as module
    def fake(url, key, body, timeout=60):
        assert url.endswith("/embeddings")
        assert body["model"] == "voyage-4-large" and body["input_type"] == "document"
        assert body["output_dimension"] == 1024 and body["truncation"] is False
        return {"data": [{"index": 1, "embedding": [2.0] * 1024}, {"index": 0, "embedding": [1.0] * 1024}], "usage": {"total_tokens": 8}}
    monkeypatch.setattr(module, "_json_post", fake)
    vectors, usage = HostedModels(Settings()).embed(["one", "two"], "document")
    assert vectors[0][0] == 1 and vectors[1][0] == 2 and usage == 8


def test_voyage_rerank_rejects_duplicate_index(monkeypatch):
    import bookrag_cloud.providers as module
    monkeypatch.setattr(module, "_json_post", lambda *args, **kwargs: {"data": [{"index": 0}, {"index": 0}]})
    with pytest.raises(ProviderError):
        HostedModels(Settings()).rerank("question", [{"text": "a"}, {"text": "b"}])


def test_sol_request_does_not_send_gold_or_page_claim(monkeypatch):
    import bookrag_cloud.providers as module
    passage_id = str(uuid4())
    def fake(url, key, body, timeout=60):
        assert url.endswith("/responses") and body["store"] is False
        assert "gold" not in body["input"].lower()
        assert passage_id in body["input"]
        return {"status": "completed", "output": [{"content": [{"type": "output_text", "text": '{"answer":"yes","supporting_passage_ids":["'+passage_id+'"],"enough_evidence":true,"event_match":"direct_answer"}'}]}], "usage": {"input_tokens": 10, "output_tokens": 2}}
    monkeypatch.setattr(module, "_json_post", fake)
    answer, usage = HostedModels(Settings()).answer("What happened?", [{"id": passage_id, "text": "It happened.", "pdf_page": 2}])
    assert answer["supporting_passage_ids"] == [passage_id] and usage["input_tokens"] == 10
