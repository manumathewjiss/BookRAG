-- Stage 2 schema for the generic book platform.
-- Exact inner-product / cosine search later uses L2-normalized vector(1024).
-- No HNSW/IVFFlat ANN index at this corpus size.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS books (
    book_id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    source TEXT,
    total_pages INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chunks (
    id TEXT PRIMARY KEY,
    book_id TEXT NOT NULL REFERENCES books (book_id) ON DELETE CASCADE,
    page INTEGER,
    chunk_index INTEGER NOT NULL,
    chunk_text TEXT NOT NULL,
    content_token_count INTEGER,
    e5_input_token_count INTEGER,
    embedding vector(1024),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (book_id, chunk_index)
);

-- BGE-M3 dense vectors are stored separately from E5 chunks.embedding.
-- Both are vector(1024); mixing them in one column would silently corrupt search.
CREATE TABLE IF NOT EXISTS chunk_embeddings_bge_m3 (
    book_id TEXT NOT NULL REFERENCES books (book_id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    embedding vector(1024) NOT NULL,
    model_name TEXT NOT NULL DEFAULT 'BAAI/bge-m3',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (book_id, chunk_index)
);

-- BGE-M3 sparse/lexical token weights for hybrid search only.
-- Does not replace dense vectors; never mixed with E5.
CREATE TABLE IF NOT EXISTS chunk_sparse_weights_bge_m3_hybrid (
    book_id TEXT NOT NULL REFERENCES books (book_id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    lexical_weights JSONB NOT NULL,
    n_nonzero INTEGER NOT NULL,
    model_name TEXT NOT NULL DEFAULT 'BAAI/bge-m3',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (book_id, chunk_index)
);
