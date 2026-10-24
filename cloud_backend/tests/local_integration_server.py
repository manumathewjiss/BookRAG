"""Local-only integration server: real FastAPI routes, simulated external systems.

Run from cloud_backend with: python -m uvicorn tests.local_integration_server:app
This module is test-only. It never reads cloud credentials or contacts providers.
"""
import re
import threading
import time
from uuid import UUID

from fastapi import Header, HTTPException

from bookrag_cloud.config import Settings
from bookrag_cloud.main import app, get_models, get_repo, get_storage
from bookrag_cloud.security import verify_access_token
from bookrag_cloud.storage import StorageError
from bookrag_cloud.worker import work_once
from tests.test_mocked_cloud_flow import MemoryRepository

USER_A = UUID("00000000-0000-4000-8000-000000000001")
USER_B = UUID("00000000-0000-4000-8000-000000000002")
cfg = Settings(allowed_origins="http://localhost:3000,http://127.0.0.1:3000")
repo = MemoryRepository()


class MemoryStorage:
    def __init__(self):
        self.objects = {}

    def upload(self, path, data):
        self.objects[path] = data

    def download(self, path):
        if path not in self.objects:
            raise StorageError("Missing test PDF")
        return self.objects[path]

    def delete(self, path):
        self.objects.pop(path, None)


class MockModels:
    def embed(self, texts, mode):
        vectors = []
        for text in texts:
            text = text.lower()
            blue = mode == "query" or "cobalt blue" in text
            vectors.append(([0.0, 1.0] if blue else [1.0, 0.0]) + [0.0] * 1022)
        return vectors, sum(len(text.split()) for text in texts)

    def rerank(self, question, passages):
        return sorted(passages, key=lambda p: "cobalt blue" not in p["text"].lower()), 20

    def answer(self, question, passages):
        if re.search(r"cobalt|second page|color", question, re.I):
            found = next((p for p in passages if "cobalt blue" in p["text"].lower()), None)
            if found:
                return {
                    "answer": "The second page says cobalt blue.",
                    "supporting_passage_ids": [str(found["id"])],
                    "enough_evidence": True,
                    "event_match": "direct_answer",
                }, {"input_tokens": 100, "output_tokens": 20}
        return {
            "answer": "The supplied passages do not confirm this.",
            "supporting_passage_ids": [],
            "enough_evidence": False,
            "event_match": "absent",
        }, {"input_tokens": 80, "output_tokens": 15}


storage = MemoryStorage()
models = MockModels()
app.dependency_overrides[get_repo] = lambda: repo
app.dependency_overrides[get_storage] = lambda: storage
app.dependency_overrides[get_models] = lambda: models


def local_auth_header(authorization: str | None = Header(default=None)):
    if authorization == f"Bearer mock.local.{USER_A}":
        return USER_A
    if authorization == "Bearer user-b":
        return USER_B
    raise HTTPException(401, "Session expired or invalid")


app.dependency_overrides[verify_access_token] = local_auth_header


def worker_loop():
    while True:
        try:
            work_once(repo, storage, models, cfg)
        except Exception:
            pass
        time.sleep(0.25)


threading.Thread(target=worker_loop, daemon=True).start()
