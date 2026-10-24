"""All database access is parameterized and explicitly scoped to an owner UUID."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import UUID

import psycopg
from psycopg.rows import dict_row


class Repository:
    def __init__(self, dsn: str):
        self.dsn = dsn

    @contextmanager
    def connection(self):
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            yield conn

    def count_today(self, owner: UUID, operation: str) -> int:
        with self.connection() as conn:
            return conn.execute(
                "select count(*) as n from usage_events where owner_id=%s and operation=%s and created_at >= date_trunc('day', now() at time zone 'UTC') at time zone 'UTC'",
                (owner, operation),
            ).fetchone()["n"]

    def reserve_question(self, owner: UUID, document_id: UUID, daily_limit: int) -> bool:
        """Serialize daily limit checks across concurrent requests for the same user."""
        with self.connection() as conn:
            conn.execute("select pg_advisory_xact_lock(hashtext(%s))", (str(owner),))
            used = conn.execute(
                "select count(*) as n from usage_events where owner_id=%s and operation='question' and created_at >= date_trunc('day', now() at time zone 'UTC') at time zone 'UTC'", (owner,)
            ).fetchone()["n"]
            if used >= daily_limit:
                return False
            conn.execute("insert into usage_events(owner_id,document_id,operation) values (%s,%s,'question')", (owner, document_id))
            return True

    def create_document(self, owner: UUID, document_id: UUID, title: str, filename: str, path: str, digest: str):
        with self.connection() as conn:
            row = conn.execute(
                "insert into documents(id,owner_id,title,filename,storage_path,sha256) values (%s,%s,%s,%s,%s,%s) returning *",
                (document_id, owner, title, filename, path, digest),
            ).fetchone()
            conn.execute("insert into ingestion_jobs(document_id) values (%s)", (document_id,))
            conn.execute("insert into usage_events(owner_id,document_id,operation) values (%s,%s,'upload')", (owner, document_id))
            return row

    def list_documents(self, owner: UUID):
        with self.connection() as conn:
            return conn.execute(
                "select * from documents where owner_id=%s and status <> 'deleted' order by created_at desc limit 200", (owner,)
            ).fetchall()

    def document(self, owner: UUID, document_id: UUID):
        with self.connection() as conn:
            return conn.execute(
                "select * from documents where owner_id=%s and id=%s and status <> 'deleted'", (owner, document_id)
            ).fetchone()

    def delete_document(self, owner: UUID, document_id: UUID):
        with self.connection() as conn:
            row = conn.execute(
                "update documents set status='deleted',updated_at=now() where owner_id=%s and id=%s and status <> 'deleted' returning storage_path", (owner, document_id)
            ).fetchone()
            if row:
                conn.execute("delete from passages where owner_id=%s and document_id=%s", (owner, document_id))
                conn.execute("delete from ingestion_jobs where document_id=%s", (document_id,))
            return row

    def passages(self, owner: UUID, document_id: UUID):
        with self.connection() as conn:
            return conn.execute(
                "select id,chunk_index,pdf_page,text from passages where owner_id=%s and document_id=%s order by chunk_index", (owner, document_id)
            ).fetchall()

    def dense_top(self, owner: UUID, document_id: UUID, vector: list[float], limit: int = 30):
        literal = "[" + ",".join(str(float(x)) for x in vector) + "]"
        with self.connection() as conn:
            return conn.execute(
                "select id,chunk_index,pdf_page,text from passages where owner_id=%s and document_id=%s order by embedding <=> %s::vector, chunk_index limit %s",
                (owner, document_id, literal, limit),
            ).fetchall()

    def claim_job(self):
        with self.connection() as conn:
            return conn.execute("""
                with picked as (
                  select j.id from ingestion_jobs j join documents d on d.id=j.document_id
                  where d.status <> 'deleted' and j.attempts < 3
                    and ((j.status='queued' and j.available_at<=now()) or (j.status='running' and j.lease_until<now()))
                  order by j.available_at for update of j skip locked limit 1
                )
                update ingestion_jobs j set status='running', attempts=j.attempts+1,
                  lease_until=now()+interval '2 hours', updated_at=now()
                from picked where j.id=picked.id
                returning j.*
            """).fetchone()

    def job_document(self, document_id: UUID):
        with self.connection() as conn:
            return conn.execute("select * from documents where id=%s and status <> 'deleted'", (document_id,)).fetchone()

    def fail_exhausted_jobs(self):
        """A worker killed during its final attempt must not leave a document processing forever."""
        with self.connection() as conn:
            rows = conn.execute("""
                update ingestion_jobs set status='failed',last_error='Processing was interrupted',updated_at=now()
                where status='running' and attempts>=3 and lease_until<now()
                returning document_id
            """).fetchall()
            for row in rows:
                conn.execute("update documents set status='failed',error='Processing was interrupted',updated_at=now() where id=%s and status <> 'deleted'", (row["document_id"],))

    def mark_processing(self, document_id: UUID):
        with self.connection() as conn:
            conn.execute("update documents set status='processing',updated_at=now() where id=%s and status <> 'deleted'", (document_id,))

    def store_passages(self, owner: UUID, document_id: UUID, rows: list[dict], page_count: int):
        with self.connection() as conn:
            current = conn.execute("select status from documents where id=%s and owner_id=%s for update", (document_id, owner)).fetchone()
            if not current or current["status"] == "deleted":
                return False
            conn.execute("delete from passages where owner_id=%s and document_id=%s", (owner, document_id))
            for row in rows:
                vec = "[" + ",".join(str(float(x)) for x in row["embedding"]) + "]"
                conn.execute(
                    "insert into passages(document_id,owner_id,chunk_index,pdf_page,text,embedding) values (%s,%s,%s,%s,%s,%s::vector)",
                    (document_id, owner, row["chunk_index"], row["pdf_page"], row["text"], vec),
                )
            conn.execute("update documents set status='ready',page_count=%s,passage_count=%s,error=null,updated_at=now() where id=%s and owner_id=%s and status <> 'deleted'", (page_count, len(rows), document_id, owner))
            conn.execute("update ingestion_jobs set status='done',updated_at=now() where document_id=%s", (document_id,))
            return True

    def job_failure(self, document_id: UUID, attempts: int, message: str):
        safe = message[:200]
        with self.connection() as conn:
            if attempts >= 3:
                conn.execute("update ingestion_jobs set status='failed',last_error=%s,updated_at=now() where document_id=%s", (safe, document_id))
                conn.execute("update documents set status='failed',error=%s,updated_at=now() where id=%s and status <> 'deleted'", (safe, document_id))
            else:
                conn.execute("update ingestion_jobs set status='queued',available_at=now()+(%s * interval '1 minute'),last_error=%s,updated_at=now() where document_id=%s", (2 ** attempts, safe, document_id))

    def record_usage(self, owner: UUID, document_id: UUID, operation: str, provider: str, input_tokens: int = 0, output_tokens: int = 0, estimated_usd: float = 0):
        with self.connection() as conn:
            conn.execute("insert into usage_events(owner_id,document_id,operation,provider,input_tokens,output_tokens,estimated_usd) values (%s,%s,%s,%s,%s,%s,%s)", (owner, document_id, operation, provider, input_tokens, output_tokens, estimated_usd))
