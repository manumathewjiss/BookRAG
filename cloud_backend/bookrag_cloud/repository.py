"""All database access is parameterized and explicitly scoped to an owner UUID."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import time
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


class UncertainEmbeddingBatch(RuntimeError):
    """A request may have reached Voyage; do not send the same batch again."""


class LostJobLease(RuntimeError):
    """A different worker owns this job, so the old worker must stop."""


class UsageLimitReached(RuntimeError):
    """An atomic user limit would be exceeded."""


class AnswerBusy(RuntimeError):
    """Another request is still preparing an answer for this document."""


class Repository:
    def __init__(self, dsn: str):
        self.dsn = dsn

    @contextmanager
    def connection(self):
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            yield conn

    @contextmanager
    def answer_lock(self, owner: UUID, document_id: UUID):
        """Serialize answers and deletion for one owner's PDF across API processes.

        A session advisory lock is released on normal exit or connection loss.
        Waiting callers never dispatch a hosted model request.
        """
        with psycopg.connect(self.dsn, autocommit=True) as conn:
            deadline = time.monotonic() + 60
            key = (str(owner), str(document_id))
            while not conn.execute(
                "select pg_try_advisory_lock(hashtext(%s), hashtext(%s)) as acquired", key
            ).fetchone()[0]:
                if time.monotonic() >= deadline:
                    raise AnswerBusy("Answer preparation is still in progress")
                time.sleep(0.25)
            try:
                yield
            finally:
                try:
                    conn.execute("select pg_advisory_unlock(hashtext(%s), hashtext(%s))", key)
                except psycopg.Error:
                    # A dead session has already released its advisory lock.
                    pass

    def count_today(self, owner: UUID, operation: str) -> int:
        with self.connection() as conn:
            return conn.execute(
                "select count(*) as n from usage_events where owner_id=%s and operation=%s and created_at >= date_trunc('day', now() at time zone 'UTC') at time zone 'UTC'",
                (owner, operation),
            ).fetchone()["n"]

    def reserve_question(self, owner: UUID, document_id: UUID, daily_limit: int,
                         daily_usd_limit: float = 5.0, reserve_usd: float = 0.05,
                         minute_limit: int = 10):
        """Serialize daily limit checks across concurrent requests for the same user."""
        with self.connection() as conn:
            conn.execute("select pg_advisory_xact_lock(hashtext(%s))", (str(owner),))
            totals = conn.execute("""
                select count(*) filter (where operation='question') as questions,
                       count(*) filter (where operation='question' and created_at>=now()-interval '1 minute') as recent_questions,
                       coalesce(sum(estimated_usd),0) as usd
                from usage_events where owner_id=%s
                  and created_at >= date_trunc('day', now() at time zone 'UTC') at time zone 'UTC'
            """, (owner,)).fetchone()
            if (totals["questions"] >= daily_limit or totals["recent_questions"] >= minute_limit
                    or float(totals["usd"]) + reserve_usd > daily_usd_limit):
                return None
            row = conn.execute("""
                insert into usage_events(owner_id,document_id,operation,estimated_usd)
                values (%s,%s,'question',%s) returning id
            """, (owner, document_id, reserve_usd)).fetchone()
            return row["id"]

    def settle_question(self, owner: UUID, event_id: UUID, input_tokens: int, output_tokens: int,
                        estimated_usd: float, *, provider: str = "voyage-4-large+rerank-3+gpt-6.1-sol"):
        """Replace the $0.05 hold with the caller's estimate. Uses migration 001 columns only."""
        with self.connection() as conn:
            conn.execute("""
                update usage_events set provider=%s,
                    input_tokens=%s, output_tokens=%s, estimated_usd=%s
                where id=%s and owner_id=%s and operation='question'
            """, (provider, input_tokens, output_tokens, estimated_usd, event_id, owner))

    def settle_reused_question(self, owner: UUID, event_id: UUID):
        """Reuse incurred no hosted calls; keep the usage row truthful at zero cost."""
        with self.connection() as conn:
            conn.execute("""
                update usage_events set provider='saved-answer-reuse',
                    input_tokens=0,output_tokens=0,estimated_usd=0
                where id=%s and owner_id=%s and operation='question'
            """, (event_id, owner))

    def create_document(self, owner: UUID, document_id: UUID, title: str, filename: str,
                        path: str, digest: str, daily_limit: int = 5):
        with self.connection() as conn:
            conn.execute("select pg_advisory_xact_lock(hashtext(%s))", (str(owner),))
            used = conn.execute("""
                select count(*) as n from usage_events where owner_id=%s and operation='upload'
                  and created_at >= date_trunc('day', now() at time zone 'UTC') at time zone 'UTC'
            """, (owner,)).fetchone()["n"]
            if used >= daily_limit:
                raise UsageLimitReached("Daily PDF upload limit reached")
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
                conn.execute("delete from embedding_batches where document_id=%s", (document_id,))
                conn.execute("delete from ingestion_jobs where document_id=%s", (document_id,))
            return row

    def delete_saved_answers(self, owner: UUID, document_id: UUID):
        """Purge cache before removing PDF bytes; failure leaves the PDF intact."""
        with self.connection() as conn:
            conn.execute(
                "delete from saved_answers where owner_id=%s and document_id=%s",
                (owner, document_id),
            )

    def list_saved_answers(self, owner: UUID, document_id: UUID, document_sha256: str, pipeline_version: str):
        with self.connection() as conn:
            return conn.execute("""
                select * from saved_answers
                where owner_id=%s and document_id=%s and document_sha256=%s and pipeline_version=%s
                order by created_at asc
            """, (owner, document_id, document_sha256, pipeline_version)).fetchall()

    def find_exact_saved_answer(self, owner: UUID, document_id: UUID, question_canonical: str,
                                document_sha256: str, pipeline_version: str):
        with self.connection() as conn:
            return conn.execute("""
                select * from saved_answers
                where owner_id=%s and document_id=%s and question_canonical=%s
                  and document_sha256=%s and pipeline_version=%s
                limit 1
            """, (owner, document_id, question_canonical, document_sha256, pipeline_version)).fetchone()

    def save_answer(self, owner: UUID, document_id: UUID, question_original: str, question_canonical: str,
                    question_signature: dict, answer_text: str, enough_evidence: bool, evidence_status: str,
                    citations: list, document_sha256: str, pipeline_version: str):
        """Insert once per strict canonical question. Concurrent writers keep the first row.

        The insert lists only columns from 004_saved_answers.sql.
        """
        with self.connection() as conn:
            conn.execute("select pg_advisory_xact_lock(hashtext(%s))", (f"{owner}:{document_id}:{question_canonical}",))
            existing = conn.execute("""
                select * from saved_answers
                where owner_id=%s and document_id=%s and question_canonical=%s
                  and document_sha256=%s and pipeline_version=%s
                limit 1
            """, (owner, document_id, question_canonical, document_sha256, pipeline_version)).fetchone()
            if existing:
                return existing
            return conn.execute("""
                insert into saved_answers(
                  owner_id, document_id, question_original, question_canonical, question_signature,
                  answer_text, enough_evidence, evidence_status, citations, document_sha256, pipeline_version
                ) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                on conflict (owner_id, document_id, question_canonical, document_sha256, pipeline_version)
                do nothing
                returning *
            """, (owner, document_id, question_original, question_canonical, Jsonb(question_signature),
                  answer_text, enough_evidence, evidence_status, Jsonb(citations), document_sha256,
                  pipeline_version)).fetchone() or conn.execute("""
                select * from saved_answers
                where owner_id=%s and document_id=%s and question_canonical=%s
                  and document_sha256=%s and pipeline_version=%s
                limit 1
            """, (owner, document_id, question_canonical, document_sha256, pipeline_version)).fetchone()

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
                    and not exists (select 1 from embedding_batches b where b.document_id=j.document_id and b.status='pending')
                  order by j.available_at for update of j skip locked limit 1
                )
                update ingestion_jobs j set status='running', attempts=j.attempts+1,
                  claim_token=gen_random_uuid(), lease_until=now()+interval '10 minutes', updated_at=now()
                from picked where j.id=picked.id
                returning j.*
            """).fetchone()

    def job_document(self, document_id: UUID):
        with self.connection() as conn:
            return conn.execute("select * from documents where id=%s and status <> 'deleted'", (document_id,)).fetchone()

    def embedding_batch_size(self, document_id: UUID) -> int | None:
        """Infer a resumable job's batch size from its first completed checkpoint."""
        with self.connection() as conn:
            row = conn.execute(
                "select status, case when status='complete' then jsonb_array_length(vectors) end as batch_size "
                "from embedding_batches where document_id=%s and batch_index=0",
                (document_id,),
            ).fetchone()
        if not row:
            return None
        if row["status"] != "complete":
            raise UncertainEmbeddingBatch("First embedding batch is not complete")
        size = row["batch_size"]
        if not 1 <= size <= 128:
            raise UncertainEmbeddingBatch("First embedding batch has invalid size")
        return size

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

    def flag_stale_pending(self):
        """Quarantine a crash after request dispatch; never automatically replay it."""
        with self.connection() as conn:
            rows = conn.execute("""
                update ingestion_jobs j set status='attention',last_error='Embedding request needs review',updated_at=now()
                where j.status='running' and j.lease_until<now()
                  and exists (select 1 from embedding_batches b where b.document_id=j.document_id and b.status='pending')
                returning j.document_id
            """).fetchall()
            for row in rows:
                conn.execute("update documents set status='failed',error='Embedding request needs review',updated_at=now() where id=%s and status <> 'deleted'", (row["document_id"],))

    def renew_job_lease(self, document_id: UUID, claim_token: UUID):
        with self.connection() as conn:
            row = conn.execute("""
                update ingestion_jobs set lease_until=now()+interval '10 minutes',updated_at=now()
                where document_id=%s and claim_token=%s and status='running' and lease_until>now()
                returning id
            """, (document_id, claim_token)).fetchone()
            if not row:
                raise LostJobLease("Job lease expired or changed")

    def begin_embedding_batch(self, document_id: UUID, claim_token: UUID, batch_index: int, digest: str):
        """Commit pending state before the external request. Return saved vectors on resume."""
        with self.connection() as conn:
            job = conn.execute("select status,claim_token,lease_until from ingestion_jobs where document_id=%s for update", (document_id,)).fetchone()
            if not job or job["status"] != "running" or job["claim_token"] != claim_token or job["lease_until"] <= datetime.now(timezone.utc):
                raise LostJobLease("Job lease expired or changed")
            row = conn.execute("select * from embedding_batches where document_id=%s and batch_index=%s for update", (document_id, batch_index)).fetchone()
            if row:
                if row["input_sha256"] != digest:
                    raise UncertainEmbeddingBatch("Saved batch input differs from the current PDF")
                if row["status"] == "complete":
                    return row["vectors"]
                raise UncertainEmbeddingBatch("Embedding batch outcome is unknown")
            conn.execute("""
                insert into embedding_batches(document_id,batch_index,input_sha256,status,claim_token)
                values (%s,%s,%s,'pending',%s)
            """, (document_id, batch_index, digest, claim_token))
            return None

    def complete_embedding_batch(self, owner: UUID, document_id: UUID, claim_token: UUID,
                                 batch_index: int, digest: str, vectors: list[list[float]], tokens: int):
        """Save response and its usage together, exactly once after a successful call."""
        with self.connection() as conn:
            job = conn.execute("select status,claim_token,lease_until from ingestion_jobs where document_id=%s for update", (document_id,)).fetchone()
            if not job or job["status"] != "running" or job["claim_token"] != claim_token or job["lease_until"] <= datetime.now(timezone.utc):
                raise LostJobLease("Job lease expired or changed")
            row = conn.execute("""
                update embedding_batches set status='complete',vectors=%s,provider_tokens=%s,updated_at=now()
                where document_id=%s and batch_index=%s and input_sha256=%s and claim_token=%s and status='pending'
                returning batch_index
            """, (Jsonb(vectors), tokens, document_id, batch_index, digest, claim_token)).fetchone()
            if not row:
                raise UncertainEmbeddingBatch("Embedding checkpoint changed during request")
            conn.execute("""
                insert into usage_events(owner_id,document_id,operation,provider,input_tokens,estimated_usd)
                values (%s,%s,'embedding','voyage-4-large',%s,%s)
            """, (owner, document_id, tokens, tokens * .12 / 1_000_000))

    def release_rejected_batch(self, document_id: UUID, claim_token: UUID, batch_index: int):
        """Only a definite provider rejection (such as HTTP 429) permits retry."""
        with self.connection() as conn:
            conn.execute("""
                delete from embedding_batches where document_id=%s and batch_index=%s
                  and claim_token=%s and status='pending'
            """, (document_id, batch_index, claim_token))

    def has_pending_batch(self, document_id: UUID) -> bool:
        with self.connection() as conn:
            return conn.execute("select 1 from embedding_batches where document_id=%s and status='pending' limit 1", (document_id,)).fetchone() is not None

    def flag_uncertain_job(self, document_id: UUID, claim_token: UUID):
        with self.connection() as conn:
            row = conn.execute("""
                update ingestion_jobs set status='attention',last_error='Embedding request needs review',updated_at=now()
                where document_id=%s and claim_token=%s and status='running' returning document_id
            """, (document_id, claim_token)).fetchone()
            if row:
                conn.execute("update documents set status='failed',error='Embedding request needs review',updated_at=now() where id=%s and status <> 'deleted'", (document_id,))

    def retry_failed_job(self, document_id: UUID) -> bool:
        """Operator retries a definite failure; completed batch checkpoints remain."""
        with self.connection() as conn:
            job = conn.execute("select status from ingestion_jobs where document_id=%s for update", (document_id,)).fetchone()
            if not job or job["status"] != "failed":
                return False
            if conn.execute("select 1 from embedding_batches where document_id=%s and status='pending' limit 1", (document_id,)).fetchone():
                return False
            conn.execute("update ingestion_jobs set status='queued',attempts=0,claim_token=null,lease_until=null,available_at=now(),last_error=null,updated_at=now() where document_id=%s", (document_id,))
            conn.execute("update documents set status='queued',error=null,updated_at=now() where id=%s and status='failed'", (document_id,))
            return True

    def clear_reviewed_batch(self, document_id: UUID, batch_index: int) -> bool:
        """Only after an operator has verified the provider did not process the request."""
        with self.connection() as conn:
            job = conn.execute("select status from ingestion_jobs where document_id=%s for update", (document_id,)).fetchone()
            if not job or job["status"] != "attention":
                return False
            row = conn.execute("delete from embedding_batches where document_id=%s and batch_index=%s and status='pending' returning batch_index", (document_id, batch_index)).fetchone()
            if not row:
                return False
            conn.execute("update ingestion_jobs set status='queued',attempts=0,claim_token=null,lease_until=null,available_at=now(),last_error=null,updated_at=now() where document_id=%s", (document_id,))
            conn.execute("update documents set status='queued',error=null,updated_at=now() where id=%s and status='failed'", (document_id,))
            return True

    def mark_processing(self, document_id: UUID, claim_token: UUID):
        with self.connection() as conn:
            row = conn.execute("""
                update documents set status='processing',updated_at=now()
                where id=%s and status <> 'deleted' and exists (
                  select 1 from ingestion_jobs where document_id=%s and claim_token=%s
                    and status='running' and lease_until>now()
                ) returning id
            """, (document_id, document_id, claim_token)).fetchone()
            if not row:
                raise LostJobLease("Job lease expired or document was deleted")

    def store_passages(self, owner: UUID, document_id: UUID, claim_token: UUID,
                       rows: list[dict], page_count: int, expected_batches: int):
        with self.connection() as conn:
            job = conn.execute("select status,claim_token,lease_until from ingestion_jobs where document_id=%s for update", (document_id,)).fetchone()
            if not job or job["status"] != "running" or job["claim_token"] != claim_token or job["lease_until"] <= datetime.now(timezone.utc):
                raise LostJobLease("Job lease expired or changed")
            count = conn.execute("select count(*) as n from embedding_batches where document_id=%s and status='complete'", (document_id,)).fetchone()["n"]
            if count != expected_batches:
                raise UncertainEmbeddingBatch("Not all embedding batches are complete")
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

    def job_failure(self, document_id: UUID, claim_token: UUID, attempts: int, message: str):
        safe = message[:200]
        with self.connection() as conn:
            owned = conn.execute("select 1 from ingestion_jobs where document_id=%s and claim_token=%s and status='running' for update", (document_id, claim_token)).fetchone()
            if not owned:
                return
            if attempts >= 3:
                conn.execute("update ingestion_jobs set status='failed',last_error=%s,updated_at=now() where document_id=%s", (safe, document_id))
                conn.execute("update documents set status='failed',error=%s,updated_at=now() where id=%s and status <> 'deleted'", (safe, document_id))
            else:
                conn.execute("update ingestion_jobs set status='queued',available_at=now()+(%s * interval '1 minute'),last_error=%s,updated_at=now() where document_id=%s", (2 ** attempts, safe, document_id))
                conn.execute("update documents set status='queued',error=null,updated_at=now() where id=%s and status <> 'deleted'", (document_id,))

    def record_usage(self, owner: UUID, document_id: UUID, operation: str, provider: str, input_tokens: int = 0, output_tokens: int = 0, estimated_usd: float = 0):
        with self.connection() as conn:
            conn.execute("insert into usage_events(owner_id,document_id,operation,provider,input_tokens,output_tokens,estimated_usd) values (%s,%s,%s,%s,%s,%s,%s)", (owner, document_id, operation, provider, input_tokens, output_tokens, estimated_usd))
