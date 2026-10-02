"""
PostgreSQL + pgvector helpers for Stage 2 storage and Stage 3 exact search.

No ANN indexes. Idempotent upserts on book_id / chunk_index.
Retrieval always filters by book_id.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Sequence

import psycopg
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parent
SCHEMA_PATH = ROOT / "schema.sql"
DEFAULT_DATABASE_URL = "postgresql://manumathewjiss@localhost:5432/books_rag"


def database_url() -> str:
    return os.environ.get("BOOKS_DATABASE_URL") or DEFAULT_DATABASE_URL


def connect(url: str | None = None) -> psycopg.Connection:
    conn = psycopg.connect(url or database_url(), row_factory=dict_row)
    register_vector(conn)
    return conn


def apply_schema(conn: psycopg.Connection) -> None:
    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()


def upsert_book(
    conn: psycopg.Connection,
    *,
    book_id: str,
    filename: str,
    source: str | None,
    total_pages: int | None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO books (book_id, filename, source, total_pages)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (book_id) DO UPDATE SET
                filename = EXCLUDED.filename,
                source = EXCLUDED.source,
                total_pages = EXCLUDED.total_pages
            """,
            (book_id, filename, source, total_pages),
        )
    conn.commit()


def upsert_chunks(conn: psycopg.Connection, rows: Sequence[dict[str, Any]]) -> None:
    """Replace chunk text/embeddings for the same book_id + chunk_index."""
    with conn.cursor() as cur:
        for row in rows:
            cur.execute(
                """
                INSERT INTO chunks (
                    id, book_id, page, chunk_index, chunk_text,
                    content_token_count, e5_input_token_count, embedding
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (book_id, chunk_index) DO UPDATE SET
                    id = EXCLUDED.id,
                    page = EXCLUDED.page,
                    chunk_text = EXCLUDED.chunk_text,
                    content_token_count = EXCLUDED.content_token_count,
                    e5_input_token_count = EXCLUDED.e5_input_token_count,
                    embedding = EXCLUDED.embedding
                """,
                (
                    row["id"],
                    row["book_id"],
                    row["page"],
                    row["chunk_index"],
                    row["chunk_text"],
                    row["content_token_count"],
                    row["e5_input_token_count"],
                    row["embedding"],
                ),
            )
    conn.commit()


def book_count(conn: psycopg.Connection) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM books")
        return int(cur.fetchone()["n"])


def chunk_count_for_book(conn: psycopg.Connection, book_id: str) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM chunks WHERE book_id = %s", (book_id,))
        return int(cur.fetchone()["n"])


def null_embedding_count(conn: psycopg.Connection, book_id: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) AS n FROM chunks WHERE book_id = %s AND embedding IS NULL",
            (book_id,),
        )
        return int(cur.fetchone()["n"])


def search_chunks(
    conn: psycopg.Connection,
    *,
    book_id: str,
    query_embedding: Sequence[float],
    top_k: int,
) -> list[dict[str, Any]]:
    """
    Exact Top-K by pgvector negative inner product (<#>).

    ORDER BY embedding <#> q ASC  ==  largest inner product first
    (same ranking as FAISS IndexFlatIP on L2-normalized vectors).
    Always filters by book_id. Does not use HNSW/IVFFlat.
    """
    vec = list(query_embedding)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                book_id,
                chunk_index,
                page,
                chunk_text,
                embedding <#> %s::vector AS neg_inner_product
            FROM chunks
            WHERE book_id = %s
              AND embedding IS NOT NULL
            ORDER BY embedding <#> %s::vector ASC
            LIMIT %s
            """,
            (vec, book_id, vec, top_k),
        )
        rows = cur.fetchall()
    hits: list[dict[str, Any]] = []
    for i, row in enumerate(rows, start=1):
        neg_ip = float(row["neg_inner_product"])
        hits.append(
            {
                "rank": i,
                "book_id": row["book_id"],
                "chunk_index": int(row["chunk_index"]),
                "page": row["page"],
                "text": row["chunk_text"],
                "neg_inner_product": neg_ip,
                "similarity": -neg_ip,
            }
        )
    return hits


def embedding_row_count(conn: psycopg.Connection, book_id: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) AS n FROM chunks WHERE book_id = %s AND embedding IS NOT NULL",
            (book_id,),
        )
        return int(cur.fetchone()["n"])


def upsert_bge_m3_embeddings(conn: psycopg.Connection, rows: Sequence[dict[str, Any]]) -> None:
    """Store BGE-M3 dense vectors only. Does not touch chunks.embedding (E5)."""
    with conn.cursor() as cur:
        for row in rows:
            cur.execute(
                """
                INSERT INTO chunk_embeddings_bge_m3 (
                    book_id, chunk_index, embedding, model_name
                )
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (book_id, chunk_index) DO UPDATE SET
                    embedding = EXCLUDED.embedding,
                    model_name = EXCLUDED.model_name
                """,
                (row["book_id"], row["chunk_index"], row["embedding"], row["model_name"]),
            )
    conn.commit()


def search_chunks_bge_m3(
    conn: psycopg.Connection,
    *,
    book_id: str,
    query_embedding: Sequence[float],
    top_k: int,
) -> list[dict[str, Any]]:
    """Exact Top-K on BGE-M3 dense vectors only. Never reads E5 chunks.embedding."""
    vec = list(query_embedding)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                c.book_id,
                c.chunk_index,
                c.page,
                c.chunk_text,
                e.embedding <#> %s::vector AS neg_inner_product
            FROM chunk_embeddings_bge_m3 e
            JOIN chunks c
              ON c.book_id = e.book_id
             AND c.chunk_index = e.chunk_index
            WHERE e.book_id = %s
            ORDER BY e.embedding <#> %s::vector ASC
            LIMIT %s
            """,
            (vec, book_id, vec, top_k),
        )
        rows = cur.fetchall()
    hits: list[dict[str, Any]] = []
    for i, row in enumerate(rows, start=1):
        neg_ip = float(row["neg_inner_product"])
        hits.append(
            {
                "rank": i,
                "book_id": row["book_id"],
                "chunk_index": int(row["chunk_index"]),
                "page": row["page"],
                "text": row["chunk_text"],
                "neg_inner_product": neg_ip,
                "similarity": -neg_ip,
            }
        )
    return hits


def bge_m3_embedding_row_count(conn: psycopg.Connection, book_id: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) AS n FROM chunk_embeddings_bge_m3 WHERE book_id = %s",
            (book_id,),
        )
        return int(cur.fetchone()["n"])


def upsert_bge_m3_hybrid_sparse_weights(conn: psycopg.Connection, rows: Sequence[dict[str, Any]]) -> None:
    """Store BGE-M3 lexical weights only. Does not touch E5 or dense BGE tables."""
    import json

    with conn.cursor() as cur:
        for row in rows:
            weights = row["lexical_weights"]
            cur.execute(
                """
                INSERT INTO chunk_sparse_weights_bge_m3_hybrid (
                    book_id, chunk_index, lexical_weights, n_nonzero, model_name
                )
                VALUES (%s, %s, %s::jsonb, %s, %s)
                ON CONFLICT (book_id, chunk_index) DO UPDATE SET
                    lexical_weights = EXCLUDED.lexical_weights,
                    n_nonzero = EXCLUDED.n_nonzero,
                    model_name = EXCLUDED.model_name
                """,
                (
                    row["book_id"],
                    row["chunk_index"],
                    json.dumps(weights),
                    int(row["n_nonzero"]),
                    row["model_name"],
                ),
            )
    conn.commit()


def load_bge_m3_hybrid_sparse_corpus(conn: psycopg.Connection, book_id: str) -> list[dict[str, Any]]:
    """Load sparse weights joined to chunk text for one book."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                c.book_id,
                c.chunk_index,
                c.page,
                c.chunk_text,
                s.lexical_weights
            FROM chunk_sparse_weights_bge_m3_hybrid s
            JOIN chunks c
              ON c.book_id = s.book_id
             AND c.chunk_index = s.chunk_index
            WHERE s.book_id = %s
            ORDER BY c.chunk_index
            """,
            (book_id,),
        )
        rows = cur.fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        weights = row["lexical_weights"]
        if isinstance(weights, str):
            import json

            weights = json.loads(weights)
        out.append(
            {
                "book_id": row["book_id"],
                "chunk_index": int(row["chunk_index"]),
                "page": row["page"],
                "text": row["chunk_text"],
                "lexical_weights": {str(k): float(v) for k, v in dict(weights).items()},
            }
        )
    return out


def bge_m3_hybrid_sparse_row_count(conn: psycopg.Connection, book_id: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) AS n FROM chunk_sparse_weights_bge_m3_hybrid WHERE book_id = %s",
            (book_id,),
        )
        return int(cur.fetchone()["n"])


def duplicate_chunk_index_count(conn: psycopg.Connection, book_id: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) AS n FROM (
                SELECT chunk_index
                FROM chunks
                WHERE book_id = %s
                GROUP BY chunk_index
                HAVING COUNT(*) > 1
            ) d
            """,
            (book_id,),
        )
        return int(cur.fetchone()["n"])
