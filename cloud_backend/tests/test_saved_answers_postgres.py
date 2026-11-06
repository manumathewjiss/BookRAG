"""Isolated PostgreSQL checks for migration 004. No production database and no model calls."""
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
]

# Local stand-in for the Supabase objects that 001–004 reference.
# Used only when BOOKRAG_ISOLATED_DATABASE_URL points at a non-Supabase database.
LOCAL_AUTH_STUB = """
create schema if not exists auth;
create table if not exists auth.users (id uuid primary key);
create or replace function auth.uid() returns uuid
language sql stable as $$ select null::uuid $$;
do $$ begin
  if not exists (select 1 from pg_roles where rolname = 'anon') then create role anon; end if;
  if not exists (select 1 from pg_roles where rolname = 'authenticated') then create role authenticated; end if;
end $$;
create schema if not exists storage;
create table if not exists storage.buckets (
  id text primary key,
  name text,
  public boolean,
  file_size_limit bigint,
  allowed_mime_types text[]
);
"""


def test_release_ships_migrations_001_through_004_only():
    names = sorted(path.name for path in (ROOT / "migrations").glob("*.sql"))
    assert names == MIGRATIONS
    text = (ROOT / "migrations" / "004_saved_answers.sql").read_text()
    assert "question_embedding" not in text
    assert "match_policy_version" not in text
    assert "create table if not exists public.saved_answers" in text


def _isolated_database_url() -> str:
    url = os.environ.get("BOOKRAG_ISOLATED_DATABASE_URL", "")
    if not url:
        pytest.skip("BOOKRAG_ISOLATED_DATABASE_URL is not set; production was not contacted")
    if "supabase.co" in url or "pooler.supabase.com" in url:
        pytest.fail("Refusing to apply migrations to a Supabase host from this test")
    return url


def _psql(url: str, args: list[str], sql: str | None = None):
    binary = os.environ.get("BOOKRAG_PSQL", "psql")
    command = [binary, url, "-v", "ON_ERROR_STOP=1", *args]
    subprocess.run(command, input=sql, text=True, stdout=subprocess.DEVNULL, check=True)


@pytest.fixture(scope="module")
def isolated_db() -> str:
    """Apply 001–004 once on a local empty database. Production is not contacted."""
    url = _isolated_database_url()
    _psql(url, [], LOCAL_AUTH_STUB)
    for name in MIGRATIONS:
        _psql(url, ["-f", str(ROOT / "migrations" / name)])
    return url


def test_migrations_001_to_004_have_no_later_columns_when_isolated_db_is_set(isolated_db):
    url = isolated_db
    import psycopg
    from psycopg.rows import dict_row

    with psycopg.connect(url, autocommit=True, row_factory=dict_row) as conn:
        saved = conn.execute("""
            select column_name from information_schema.columns
            where table_schema = 'public' and table_name = 'saved_answers'
            order by ordinal_position
        """).fetchall()
        usage = conn.execute("""
            select column_name from information_schema.columns
            where table_schema = 'public' and table_name = 'usage_events'
        """).fetchall()
        indexes = conn.execute("""
            select indexdef from pg_indexes
            where schemaname = 'public' and tablename = 'saved_answers'
        """).fetchall()
    saved_names = [row["column_name"] for row in saved]
    usage_names = {row["column_name"] for row in usage}
    assert saved_names == [
        "id", "owner_id", "document_id", "question_original", "question_canonical",
        "question_signature", "answer_text", "enough_evidence", "evidence_status",
        "citations", "document_sha256", "pipeline_version", "created_at",
    ]
    assert "estimated_usd" in usage_names
    assert "cost_breakdown" not in usage_names
    assert "cost_certainty" not in usage_names
    joined = "\n".join(row["indexdef"] for row in indexes)
    assert "owner_id, document_id, question_canonical, document_sha256, pipeline_version" in joined


def test_exact_lookup_on_004_ignores_legacy_keys_and_records_latency(isolated_db):
    url = isolated_db
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
    citation = {"passage_id": str(uuid4()), "pdf_page": 3, "excerpt": "Neil Armstrong walked on the Moon."}
    stored = repo.save_answer(
        owner, document_id, question, canonical, question_signature(question),
        "Neil Armstrong walked on the Moon.", True, "direct_answer",
        [citation], digest, ANSWER_PIPELINE_VERSION,
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
    with ThreadPoolExecutor(max_workers=3) as pool:
        holder = pool.submit(hold)
        time.sleep(0.05)
        locked = pool.submit(lambda: _locked_lookup(repo, owner, document_id, canonical, digest))
        holder.result()
        locked_row, locked_ms = locked.result()
    assert stored["answer_text"] == found["answer_text"] == "Neil Armstrong walked on the Moon."
    assert found["citations"] == [citation]
    assert missing is None
    assert locked_row["answer_text"] == found["answer_text"]
    assert locked_row["citations"] == [citation]
    report = {
        "mode": "postgresql_16_migrations_001_to_004",
        "paid_api_calls": 0,
        "indexed_hit_ms": round(hit_ms, 3),
        "indexed_miss_ms": round(miss_ms, 3),
        "lock_waiter_ms": round(locked_ms, 3),
        "later_migration_columns_present": False,
    }
    print(json.dumps(report))
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
