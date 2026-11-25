"""Labeled eval-set checks and isolated migration checks. No production database."""
import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = [
    "001_initial.sql",
    "002_embedding_checkpoints.sql",
    "003_cloud_readiness.sql",
    "004_saved_answers.sql",
    "005_saved_answer_question_embeddings.sql",
    "006_usage_cost_breakdown.sql",
]


def test_eval_set_has_independent_splits_and_no_model_scores():
    path = ROOT / "benchmarks" / "verifier_eval_set.json"
    if not path.exists():
        subprocess.check_call(["python3", str(ROOT / "benchmarks" / "build_verifier_eval_set.py")])
    data = json.loads(path.read_text())
    assert data["paid_api_calls"] == 0
    assert data["model_scored"] is False
    dev = [row for row in data["pairs"] if row["split"] == "dev"]
    held = [row for row in data["pairs"] if row["split"] == "heldout"]
    assert len(dev) == 60
    assert len(held) == 240
    assert {row["pair_id"] for row in dev}.isdisjoint({row["pair_id"] for row in held})
    assert {(row["saved_question"], row["new_question"]) for row in dev}.isdisjoint(
        {(row["saved_question"], row["new_question"]) for row in held}
    )
    hard = [row for row in data["pairs"] if row["critical_hard_negative"]]
    assert hard
    assert all(row["expected"] == "RUN_FULL_RAG" for row in hard)


def test_live_eval_command_is_refused():
    script = ROOT / "benchmarks" / "verifier_eval_plan.py"
    completed = subprocess.run(["python3", str(script), "--live"], capture_output=True, text=True)
    assert completed.returncode == 2
    assert "REFUSED" in completed.stdout


def test_migration_files_are_ordered_and_additive_after_003():
    names = sorted(path.name for path in (ROOT / "migrations").glob("*.sql"))
    assert names == MIGRATIONS
    text_005 = (ROOT / "migrations" / "005_saved_answer_question_embeddings.sql").read_text()
    text_006 = (ROOT / "migrations" / "006_usage_cost_breakdown.sql").read_text()
    assert "add column if not exists question_embedding" in text_005
    assert "drop table" not in text_005.lower()
    assert "add column if not exists cost_breakdown" in text_006
    assert "drop table" not in text_006.lower()


def _isolated_database_url() -> str:
    url = os.environ.get("BOOKRAG_ISOLATED_DATABASE_URL", "")
    if not url:
        pytest.skip("BOOKRAG_ISOLATED_DATABASE_URL is not set; production was not contacted")
    if "supabase.co" in url or "pooler.supabase.com" in url:
        pytest.fail("Refusing to apply migrations to a Supabase host from this test")
    return url


def _psql(url: str, args: list[str]):
    binary = os.environ.get("BOOKRAG_PSQL", "psql")
    subprocess.check_call([binary, url, "-v", "ON_ERROR_STOP=1", *args], stdout=subprocess.DEVNULL)


def test_migrations_004_apply_without_005_or_006_when_isolated_db_is_set():
    """Apply 001–004 only. Production is not contacted. 005 and 006 stay absent."""
    url = _isolated_database_url()
    for name in MIGRATIONS[:4]:
        _psql(url, ["-f", str(ROOT / "migrations" / name)])
    import psycopg
    from psycopg.rows import dict_row

    with psycopg.connect(url, autocommit=True, row_factory=dict_row) as conn:
        saved = conn.execute("""
            select column_name from information_schema.columns
            where table_schema = 'public' and table_name = 'saved_answers'
        """).fetchall()
        usage = conn.execute("""
            select column_name from information_schema.columns
            where table_schema = 'public' and table_name = 'usage_events'
        """).fetchall()
    saved_names = {row["column_name"] for row in saved}
    usage_names = {row["column_name"] for row in usage}
    assert "question_canonical" in saved_names
    assert "question_embedding" not in saved_names
    assert "match_policy_version" not in saved_names
    assert "estimated_usd" in usage_names
    assert "cost_breakdown" not in usage_names
    assert "cost_certainty" not in usage_names


def test_exact_lookup_on_004_ignores_legacy_keys_and_records_latency():
    url = _isolated_database_url()
    import time
    from uuid import uuid4

    import psycopg
    from psycopg.rows import dict_row

    from bookrag_cloud.question_match import (
        ANSWER_PIPELINE_VERSION,
        LEGACY_PIPELINE_VERSION,
        canonicalize_question,
        question_signature,
    )
    from bookrag_cloud.repository import Repository

    owner, document_id = uuid4(), uuid4()
    digest = "a" * 64
    question = "Who is Neil Armstrong?"
    canonical = canonicalize_question(question)
    with psycopg.connect(url, autocommit=True, row_factory=dict_row) as conn:
        conn.execute("insert into auth.users(id) values (%s) on conflict do nothing", (owner,))
        conn.execute("""
            insert into documents(id, owner_id, title, filename, storage_path, sha256, status)
            values (%s,%s,'Apollo','apollo.pdf',%s,%s,'ready')
        """, (document_id, owner, f"{owner}/{document_id}/source.pdf", digest))
        conn.execute("""
            insert into saved_answers(
              owner_id, document_id, question_original, question_canonical, question_signature,
              answer_text, enough_evidence, evidence_status, citations, document_sha256, pipeline_version
            ) values (%s,%s,%s,%s,%s::jsonb,%s,true,'direct_answer','[]'::jsonb,%s,%s)
        """, (owner, document_id, question, "who be neil armstrong", '{"policy":"legacy"}',
              "Legacy answer", digest, LEGACY_PIPELINE_VERSION))
    repo = Repository(url)
    assert repo.find_exact_saved_answer(
        owner, document_id, canonical, digest, ANSWER_PIPELINE_VERSION
    ) is None
    assert repo.find_exact_saved_answer(
        owner, document_id, "who be neil armstrong", digest, ANSWER_PIPELINE_VERSION
    ) is None
    stored = repo.save_answer(
        owner, document_id, question, canonical, question_signature(question),
        "Neil Armstrong walked on the Moon.", True, "direct_answer",
        [{"passage_id": str(uuid4()), "pdf_page": 3, "excerpt": "Neil Armstrong walked on the Moon."}],
        digest, ANSWER_PIPELINE_VERSION,
    )
    started = time.perf_counter()
    found = repo.find_exact_saved_answer(owner, document_id, canonical, digest, ANSWER_PIPELINE_VERSION)
    hit_ms = (time.perf_counter() - started) * 1000
    miss_started = time.perf_counter()
    missing = repo.find_exact_saved_answer(
        owner, document_id, canonicalize_question("Who was Neil Armstrong?"), digest, ANSWER_PIPELINE_VERSION,
    )
    miss_ms = (time.perf_counter() - miss_started) * 1000

    def hold():
        with repo.answer_lock(owner, document_id):
            time.sleep(0.3)

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=2) as pool:
        holder = pool.submit(hold)
        time.sleep(0.05)
        wait_started = time.perf_counter()
        waiter = pool.submit(lambda: repo.find_exact_saved_answer(
            owner, document_id, canonical, digest, ANSWER_PIPELINE_VERSION,
        ))
        # The waiter above does not take the lock. Take the lock to measure contention.
        locked = pool.submit(lambda: _locked_lookup(repo, owner, document_id, canonical, digest))
        holder.result()
        locked_row, locked_ms = locked.result()
        waiter.result()
    assert stored["answer_text"] == found["answer_text"] == "Neil Armstrong walked on the Moon."
    assert missing is None
    assert locked_row["answer_text"] == found["answer_text"]
    report = {
        "mode": "postgresql_16_migrations_001_to_004",
        "paid_api_calls": 0,
        "indexed_hit_ms": round(hit_ms, 3),
        "indexed_miss_ms": round(miss_ms, 3),
        "lock_waiter_ms": round(locked_ms, 3),
        "columns_005_present": False,
        "columns_006_present": False,
    }
    (ROOT / "benchmarks" / "strict_v1_postgres_latency.json").write_text(json.dumps(report, indent=2) + "\n")
    assert hit_ms < 50
    assert miss_ms < 50
    assert locked_ms >= 200


def _locked_lookup(repo, owner, document_id, canonical, digest):
    import time
    from bookrag_cloud.question_match import ANSWER_PIPELINE_VERSION
    started = time.perf_counter()
    with repo.answer_lock(owner, document_id):
        row = repo.find_exact_saved_answer(owner, document_id, canonical, digest, ANSWER_PIPELINE_VERSION)
    return row, (time.perf_counter() - started) * 1000
