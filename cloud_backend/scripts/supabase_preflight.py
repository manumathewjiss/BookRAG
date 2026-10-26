"""Read-only schema/security checks. No network unless --execute is supplied."""
import argparse
import json

from bookrag_cloud.config import settings
from bookrag_cloud.repository import Repository


def inspect(conn) -> dict:
    tables = {r["relname"]: r["relrowsecurity"] for r in conn.execute("""
        select c.relname, c.relrowsecurity from pg_class c
        join pg_namespace n on n.oid=c.relnamespace
        where n.nspname='public' and c.relname = any(%s)
    """, (["documents", "passages", "ingestion_jobs", "embedding_batches", "usage_events"],)).fetchall()}
    policies = {(r["tablename"], r["policyname"]) for r in conn.execute("""
        select tablename, policyname from pg_policies where schemaname='public'
    """).fetchall()}
    bucket = conn.execute("""
        select public, file_size_limit, allowed_mime_types from storage.buckets
        where id='bookrag-pdfs'
    """).fetchone()
    dimension = conn.execute("""
        select format_type(a.atttypid,a.atttypmod) as type from pg_attribute a
        where a.attrelid='public.passages'::regclass and a.attname='embedding'
    """).fetchone()["type"]
    client_can_write = conn.execute("""
        select has_table_privilege('authenticated', 'public.documents', 'INSERT')
          or has_table_privilege('authenticated', 'public.passages', 'INSERT')
          or has_table_privilege('authenticated', 'public.embedding_batches', 'SELECT')
          or has_table_privilege('anon', 'public.documents', 'SELECT') as unsafe
    """).fetchone()["unsafe"]
    owner_fk = conn.execute("""
        select exists(select 1 from pg_constraint where conname='passages_document_owner_fk') as present
    """).fetchone()["present"]
    storage_policies = conn.execute("""
        select policyname, cmd, roles, qual, with_check from pg_policies
        where schemaname='storage' and tablename='objects'
    """).fetchall()
    checks = {
        "all_tables_have_rls": len(tables) == 5 and all(tables.values()),
        "owner_select_policies": {("documents", "documents_owner_select"),
                                   ("passages", "passages_owner_select"),
                                   ("usage_events", "usage_owner_select")} <= policies,
        "vector_1024": dimension == "vector(1024)",
        "private_pdf_bucket": bool(bucket and not bucket["public"] and
                                   bucket["file_size_limit"] == 26214400 and
                                   bucket["allowed_mime_types"] == ["application/pdf"]),
        "client_table_grants_restricted": not client_can_write,
        "passage_document_owner_fk": owner_fk,
        "storage_object_policies_need_manual_review": len(storage_policies) == 0,
    }
    return {"checks": checks, "pass": all(checks.values()),
            "storage_policy_count": len(storage_policies)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="Connect read-only to configured Supabase Postgres")
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps({"mode": "dry_run", "online_checks": 7, "network_calls": 0}))
        return
    cfg = settings()
    if not cfg.database_url:
        raise SystemExit("DATABASE_URL is missing")
    repo = Repository(cfg.database_url)
    with repo.connection() as conn:
        conn.execute("set transaction read only")
        report = inspect(conn)
    print(json.dumps(report, indent=2))
    if not report["pass"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
