"""Strict v1 regressions and local latency. No paid provider calls."""
import json
import time
from concurrent.futures import ThreadPoolExecutor

from bookrag_cloud.main import chat
from bookrag_cloud.providers import ProviderError, ProviderUncertainCharge
from bookrag_cloud.question_match import ANSWER_PIPELINE_VERSION, LEGACY_PIPELINE_VERSION, canonicalize_question
from bookrag_cloud.schemas import ChatRequest

from .test_saved_answers import DIGEST, DOC, MemorySavedRepo, OWNER, PASSAGE, TrackingModels


def test_legacy_pipeline_row_is_not_reused():
    repo, models = MemorySavedRepo(), TrackingModels()
    legacy = canonicalize_question("Who is Neil Armstrong?").lower()
    repo.saved.append({
        "owner_id": OWNER,
        "document_id": DOC,
        "question_original": "Who is Neil Armstrong?",
        "question_canonical": legacy,
        "question_signature": {"policy": "legacy"},
        "answer_text": "Legacy answer that must not be reused.",
        "enough_evidence": True,
        "evidence_status": "direct_answer",
        "citations": [{"passage_id": str(PASSAGE), "pdf_page": 3, "excerpt": "legacy"}],
        "document_sha256": DIGEST,
        "pipeline_version": LEGACY_PIPELINE_VERSION,
        "created_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc),
    })
    answer = chat(DOC, ChatRequest(question="Who is Neil Armstrong?"), OWNER, repo, models)
    assert answer.reused_answer is False
    assert answer.answer != "Legacy answer that must not be reused."
    assert models.embed_calls == 1 and models.answer_calls == 1
    assert repo.saved[-1]["pipeline_version"] == ANSWER_PIPELINE_VERSION
    assert repo.saved[-1]["question_canonical"] == "Who is Neil Armstrong"


def test_cache_hit_miss_and_lock_contention_latency(tmp_path, monkeypatch):
    repo, models = MemorySavedRepo(), TrackingModels()
    question = ChatRequest(question="Who is Neil Armstrong?")
    miss_started = time.perf_counter()
    first = chat(DOC, question, OWNER, repo, models)
    miss_ms = (time.perf_counter() - miss_started) * 1000
    assert first.reused_answer is False

    hit_started = time.perf_counter()
    second = chat(DOC, ChatRequest(question="  Who is Neil Armstrong ? "), OWNER, repo, models)
    hit_ms = (time.perf_counter() - hit_started) * 1000
    assert second.reused_answer is True
    assert second.answer == first.answer
    assert models.embed_calls == 1

    class SlowAnswer(TrackingModels):
        def answer(self, question, passages):
            time.sleep(0.12)
            return super().answer(question, passages)

    busy, slow = MemorySavedRepo(), SlowAnswer()

    def ask(text):
        started = time.perf_counter()
        result = chat(DOC, ChatRequest(question=text), OWNER, busy, slow)
        return result, (time.perf_counter() - started) * 1000

    with ThreadPoolExecutor(max_workers=2) as pool:
        held = pool.submit(ask, "Who is Neil Armstrong?")
        time.sleep(0.02)
        waited = pool.submit(ask, "Who is Neil Armstrong?")
        held_result, held_ms = held.result()
        waited_result, waited_ms = waited.result()
    assert held_result.reused_answer is False
    assert waited_result.reused_answer is True
    assert slow.answer_calls == 1
    assert waited_ms >= 50

    report = {
        "mode": "in_memory_lock",
        "paid_api_calls": 0,
        "cache_miss_ms": round(miss_ms, 3),
        "cache_hit_without_contention_ms": round(hit_ms, 3),
        "holder_ms": round(held_ms, 3),
        "waiter_ms": round(waited_ms, 3),
        "waiter_reused": True,
        "duplicate_paid_answers": 0,
    }
    (tmp_path / "strict_v1_latency.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))
    assert hit_ms < 100
    assert miss_ms < 100


def test_provider_timeout_keeps_reservation_without_new_columns():
    class TimeoutEmbed(TrackingModels):
        def embed(self, texts, mode):
            raise ProviderUncertainCharge("timeout")

    repo, models = MemorySavedRepo(), TimeoutEmbed()
    try:
        chat(DOC, ChatRequest(question="Who is Neil Armstrong?"), OWNER, repo, models)
        raise AssertionError("timeout must not return an answer")
    except Exception as exc:
        from fastapi import HTTPException
        assert isinstance(exc, HTTPException)
        assert exc.status_code == 503
    args, kwargs = repo.settled[-1]
    assert args[4] >= 0.05
    assert "cost_breakdown" not in kwargs
    assert "cost_certainty" not in kwargs


def test_rejected_provider_call_does_not_keep_the_full_reservation():
    class RejectEmbed(TrackingModels):
        def embed(self, texts, mode):
            raise ProviderError("rejected")

    repo, models = MemorySavedRepo(), RejectEmbed()
    from fastapi import HTTPException
    try:
        chat(DOC, ChatRequest(question="Who is Neil Armstrong?"), OWNER, repo, models)
    except HTTPException as exc:
        assert exc.status_code == 503
    else:
        raise AssertionError("rejection must not return an answer")
    args, kwargs = repo.settled[-1]
    assert args[4] == 0
    assert kwargs["provider"] == "rejected"
