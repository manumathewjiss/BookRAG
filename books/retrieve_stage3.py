"""
Stage 3 retrieval: question → query: E5 → exact pgvector Top-K.

Does not re-embed passages, re-chunk PDFs, or generate answers.
"""

from __future__ import annotations

import argparse
import os
import sys

import numpy as np

from db import connect, search_chunks

E5_MODEL = "intfloat/multilingual-e5-large"
QUERY_PREFIX = "query: "
EXPECTED_DIM = 1024
NORM_ATOL = 1e-3


def query_input(question: str) -> str:
    return QUERY_PREFIX + question


def load_e5_encoder(model_name: str = E5_MODEL, device: str = "cpu"):
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(model_name, device=device)
    model.eval()
    return model


def embed_query(model, question: str, *, device: str = "cpu") -> tuple[np.ndarray, dict]:
    import torch

    text = query_input(question)
    with torch.inference_mode():
        vec = model.encode(
            [text],
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
            device=device,
        )
    vec = np.asarray(vec, dtype=np.float32)
    if vec.ndim != 2 or vec.shape[0] != 1:
        raise RuntimeError(f"Unexpected query embedding shape: {vec.shape}")
    dim = int(vec.shape[1])
    if dim != EXPECTED_DIM:
        raise RuntimeError(f"Query embedding dim {dim} != {EXPECTED_DIM}")
    if not np.isfinite(vec).all():
        raise RuntimeError("Query embedding contains NaN or inf.")
    norm = float(np.linalg.norm(vec[0]))
    if abs(norm - 1.0) > NORM_ATOL:
        raise RuntimeError(f"Query embedding is not unit-normalized: norm={norm}")
    stats = {
        "model": getattr(model, "model_name", E5_MODEL) if hasattr(model, "model_name") else E5_MODEL,
        "query_prefix": QUERY_PREFIX,
        "dimension": dim,
        "norm": norm,
        "normalized": True,
    }
    return vec[0], stats


def retrieve(
    question: str,
    *,
    book_id: str,
    top_k: int = 5,
    device: str = "cpu",
    model=None,
) -> dict:
    own_model = model is None
    if own_model:
        model = load_e5_encoder(device=device)
    qvec, qstats = embed_query(model, question, device=device)
    conn = connect()
    try:
        hits = search_chunks(
            conn, book_id=book_id, query_embedding=qvec.tolist(), top_k=top_k
        )
    finally:
        conn.close()
    return {
        "question": question,
        "book_id": book_id,
        "top_k": top_k,
        "query_embedding": qstats,
        "hits": hits,
    }


def print_retrieval(result: dict) -> None:
    qe = result["query_embedding"]
    print("Question:")
    print(result["question"])
    print()
    print(f"Query prefix: {qe['query_prefix']!r}")
    print(f"Query embedding dimension: {qe['dimension']}")
    print(f"Query embedding norm: {qe['norm']:.6f}")
    print(f"Book filter: {result['book_id']}")
    print()
    if not result["hits"]:
        print("No hits returned.")
        return
    for hit in result["hits"]:
        print(f"Rank {hit['rank']}")
        print(f"Page: {hit['page']}")
        print(f"Chunk index: {hit['chunk_index']}")
        print(f"Similarity (inner product): {hit['similarity']:.6f}")
        print("Original text:")
        print(hit["text"])
        print()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Stage 3: retrieve Top-K chunks for a question.")
    p.add_argument("--book-id", default="thinkpython")
    p.add_argument("--question", required=True)
    p.add_argument("--top-k", type=int, default=5)
    p.add_argument("--device", default="cpu")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = retrieve(
        args.question,
        book_id=args.book_id,
        top_k=max(1, args.top_k),
        device=args.device,
    )
    print_retrieval(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
