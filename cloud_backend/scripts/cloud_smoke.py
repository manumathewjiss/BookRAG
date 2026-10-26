"""Opt-in real Supabase + Voyage + OpenAI smoke. Default is offline dry-run.

Run from cloud_backend. Never paste tokens or API keys into command arguments.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient

from bookrag_cloud.chunking import extract_chunks
from bookrag_cloud.config import settings
from bookrag_cloud.main import app, get_models, get_repo, get_storage
from bookrag_cloud.providers import HostedModels
from bookrag_cloud.repository import Repository
from bookrag_cloud.storage import PrivateStorage
from bookrag_cloud.verification_guard import GuardedModels
from bookrag_cloud.worker import work_once
from tests.pdf_fixture import two_page_pdf

FIRST = "The first page names the metal copper."
SECOND = "The second page names the color cobalt blue."
QUESTION = "What color does the second PDF page name?"
UNKNOWN = "What is the author's email address in this PDF?"
RUN_DIR = Path("verification_runs")


def fixture() -> tuple[bytes, dict]:
    pdf = two_page_pdf(FIRST, SECOND)
    pages, rows = extract_chunks(pdf, 10, 100)
    if pages != 2 or {r["pdf_page"] for r in rows} != {1, 2}:
        raise RuntimeError("PDF page mapping changed")
    return pdf, {"sha256": hashlib.sha256(pdf).hexdigest(), "pages": pages,
                 "passages": len(rows), "document_embedding_batches": (len(rows) + 31) // 32,
                 "max_voyage_requests": 5, "max_openai_requests": 2,
                 "max_voyage_usd": 0.02, "max_openai_usd": 0.10,
                 "questions": [QUESTION, UNKNOWN]}


def approval_ok(path: Path, expected: dict) -> bool:
    try:
        approval = json.loads(path.read_text())
    except (OSError, ValueError):
        return False
    return approval == {"approved": True, "pdf_sha256": expected["sha256"],
                        "max_voyage_requests": 5, "max_openai_requests": 2,
                        "max_voyage_usd": 0.02, "max_openai_usd": 0.10}


def check_database_rls(repo: Repository, document_id: UUID, owner_a: UUID, owner_b: UUID) -> None:
    """Use the authenticated Postgres role to test RLS, not the backend role."""
    for owner, expected in ((owner_a, True), (owner_b, False)):
        with repo.connection() as conn:
            conn.execute("set transaction read only")
            conn.execute("set local role authenticated")
            conn.execute("select set_config('request.jwt.claim.sub', %s, true)", (str(owner),))
            visible = conn.execute("select exists(select 1 from public.documents where id=%s) as yes",
                                   (document_id,)).fetchone()["yes"]
            if visible != expected:
                raise RuntimeError("Database row-level user isolation failed")


def execute(pdf: bytes, manifest: dict, run_file: Path) -> dict:
    cfg = settings()
    required = (cfg.database_url, cfg.supabase_url, cfg.supabase_service_role_key,
                cfg.voyage_api_key, cfg.openai_api_key,
                os.getenv("BOOKRAG_SMOKE_USER_A_TOKEN"), os.getenv("BOOKRAG_SMOKE_USER_B_TOKEN"))
    if not all(required):
        raise RuntimeError("Required cloud settings or two user sessions are missing")
    guard = GuardedModels(HostedModels(cfg))
    repo, storage = Repository(cfg.database_url), PrivateStorage(cfg)
    # A dedicated empty verification project prevents work_once from claiming a
    # different user's queued job, and avoids disturbing existing worker state.
    with repo.connection() as conn:
        for table in ("documents", "ingestion_jobs", "embedding_batches"):
            if conn.execute(f"select exists(select 1 from public.{table}) as busy").fetchone()["busy"]:
                raise RuntimeError("Verification requires a dedicated empty Supabase project")
    app.dependency_overrides[get_repo] = lambda: repo
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[get_models] = lambda: guard
    headers_a = {"Authorization": "Bearer " + required[-2]}
    headers_b = {"Authorization": "Bearer " + required[-1]}
    result = {"status": "started", "pdf_sha256": manifest["sha256"]}
    try:
        with TestClient(app) as client:
            a = client.get("/api/v1/me", headers=headers_a)
            b = client.get("/api/v1/me", headers=headers_b)
            if a.status_code != 200 or b.status_code != 200 or a.json()["user_id"] == b.json()["user_id"]:
                raise RuntimeError("Two distinct authenticated users are required")
            uploaded = client.post("/api/v1/documents", headers=headers_a,
                                   files={"file": ("bookrag-cloud-smoke.pdf", pdf, "application/pdf")})
            if uploaded.status_code != 202:
                raise RuntimeError(f"Upload failed with HTTP {uploaded.status_code}")
            document_id = UUID(uploaded.json()["document"]["id"])
            result["document_id"] = str(document_id)
            result["status"] = "uploaded"
            run_file.write_text(json.dumps(result, indent=2))
            check_database_rls(repo, document_id, UUID(a.json()["user_id"]), UUID(b.json()["user_id"]))
            path = f"/api/v1/documents/{document_id}"
            if (client.get(path, headers=headers_b).status_code != 404
                    or client.get(path + "/pdf", headers=headers_b).status_code != 404
                    or client.delete(path, headers=headers_b).status_code != 404):
                raise RuntimeError("Cross-user document isolation failed")
            if any(x["id"] == str(document_id) for x in client.get("/api/v1/documents", headers=headers_b).json()["documents"]):
                raise RuntimeError("Cross-user library isolation failed")
            if client.get(path + "/pdf", headers=headers_a).content != pdf:
                raise RuntimeError("Private PDF bytes changed")
            if not work_once(repo, storage, guard, cfg):
                raise RuntimeError("Ingestion job was not claimed")
            document = client.get(path, headers=headers_a).json()["document"]
            if document["status"] != "ready" or document["page_count"] != 2:
                raise RuntimeError("Document did not finish with two PDF pages")
            rows = repo.passages(UUID(a.json()["user_id"]), document_id)
            if not any(r["pdf_page"] == 2 and "cobalt blue" in r["text"] for r in rows):
                raise RuntimeError("Second-page passage missing")
            result["status"] = "indexed"
            run_file.write_text(json.dumps(result, indent=2))
            if client.post(path + "/chat", headers=headers_b, json={"question": QUESTION}).status_code != 404:
                raise RuntimeError("Cross-user chat isolation failed")
            answer = client.post(path + "/chat", headers=headers_a, json={"question": QUESTION})
            if answer.status_code != 200:
                raise RuntimeError(f"Answer failed with HTTP {answer.status_code}")
            answer_data = answer.json()
            if (not answer_data["enough_evidence"] or "cobalt blue" not in answer_data["answer"].lower()
                    or not any(c["pdf_page"] == 2 and "cobalt blue" in c["excerpt"] for c in answer_data["citations"])):
                raise RuntimeError("Answer or page citation was not supported")
            missing = client.post(path + "/chat", headers=headers_a, json={"question": UNKNOWN})
            if missing.status_code != 200 or missing.json()["enough_evidence"] or missing.json()["citations"]:
                raise RuntimeError("Unanswerable question was not refused")
            result["status"] = "answered"
            run_file.write_text(json.dumps(result, indent=2))
            if client.delete(path, headers=headers_a).status_code != 204:
                raise RuntimeError("Deletion failed")
            if client.get(path, headers=headers_a).status_code != 404:
                raise RuntimeError("Deleted document remains visible")
            result.update(status="passed", pages=2, citations_checked=len(answer_data["citations"]),
                          isolation_checks="passed", abstention="passed", usage=guard.summary())
            return result
    finally:
        app.dependency_overrides.clear()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="Requires a separate, exact approval file")
    parser.add_argument("--approval-file", type=Path)
    args = parser.parse_args()
    pdf, manifest = fixture()
    if not args.execute:
        print(json.dumps({"mode": "dry_run", **manifest}, indent=2))
        return
    if not args.approval_file or not approval_ok(args.approval_file, manifest):
        raise SystemExit("Live verification requires an exact approval file")
    RUN_DIR.mkdir(exist_ok=True)
    run_file = RUN_DIR / (manifest["sha256"][:16] + ".json")
    # Exclusive creation blocks accidental re-execution after any interruption.
    with run_file.open("x") as output:
        json.dump({"status": "pending", "pdf_sha256": manifest["sha256"]}, output)
    try:
        result = execute(pdf, manifest, run_file)
    except Exception as exc:
        last = json.loads(run_file.read_text())
        run_file.write_text(json.dumps({**last, "status": "attention", "error_type": type(exc).__name__}, indent=2))
        raise
    run_file.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
