"""
BGE-M3 sparse/lexical weights (FlagEmbedding documented formula).

Uses the same BAAI/bge-m3 encoder plus sparse_linear.pt:
    w_t = ReLU(W_lex^T h_i); repeated tokens keep max weight.
Lexical score is sum over shared token ids of w_q[t] * w_d[t].

Does not compute BM25, ColBERT, or a new embedding family.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

import numpy as np
import torch
from huggingface_hub import hf_hub_download
from transformers import AutoModel, AutoTokenizer

BGE_MODEL = "BAAI/bge-m3"
SPARSE_LINEAR_FILE = "sparse_linear.pt"
UNUSED_SPECIALS = ("cls_token", "eos_token", "pad_token", "unk_token")


class BgeM3SparseEncoder:
    def __init__(self, model_name: str = BGE_MODEL, device: str = "cpu", max_length: int = 512):
        self.model_name = model_name
        self.device = device
        self.max_length = max_length
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.encoder = AutoModel.from_pretrained(model_name)
        hidden = int(self.encoder.config.hidden_size)
        self.sparse_linear = torch.nn.Linear(hidden, 1)
        linear_path = hf_hub_download(model_name, SPARSE_LINEAR_FILE)
        state = torch.load(linear_path, map_location="cpu", weights_only=True)
        self.sparse_linear.load_state_dict(state)
        self.encoder.to(device)
        self.sparse_linear.to(device)
        self.encoder.eval()
        self.sparse_linear.eval()
        self.unused_token_ids = set()
        for name in UNUSED_SPECIALS:
            if name in self.tokenizer.special_tokens_map:
                tok = self.tokenizer.special_tokens_map[name]
                self.unused_token_ids.add(self.tokenizer.convert_tokens_to_ids(tok))

    def encode_lexical_weights(self, texts: list[str], *, batch_size: int = 8) -> list[dict[str, float]]:
        out: list[dict[str, float]] = []
        with torch.inference_mode():
            for start in range(0, len(texts), batch_size):
                batch = texts[start : start + batch_size]
                encoded = self.tokenizer(
                    batch,
                    padding=True,
                    truncation=True,
                    max_length=self.max_length,
                    return_tensors="pt",
                )
                encoded = {k: v.to(self.device) for k, v in encoded.items()}
                hidden = self.encoder(**encoded).last_hidden_state
                token_weights = torch.relu(self.sparse_linear(hidden)).squeeze(-1).cpu().numpy()
                input_ids = encoded["input_ids"].cpu().numpy()
                for weights_row, ids_row in zip(token_weights, input_ids):
                    out.append(self._process_token_weights(weights_row, ids_row.tolist()))
        return out

    def _process_token_weights(self, token_weights: np.ndarray, input_ids: list[int]) -> dict[str, float]:
        result: dict[str, float] = {}
        for weight, token_id in zip(token_weights, input_ids):
            w = float(weight)
            if token_id in self.unused_token_ids or w <= 0:
                continue
            key = str(int(token_id))
            if w > result.get(key, 0.0):
                result[key] = w
        return result


def lexical_matching_score(query_weights: dict[str, float], doc_weights: dict[str, float]) -> float:
    score = 0.0
    for token, weight in query_weights.items():
        dw = doc_weights.get(token)
        if dw is not None:
            score += weight * dw
    return float(score)


def build_sparse_index(corpus: Iterable[dict[str, Any]]) -> dict[str, list[tuple[int, float]]]:
    index: dict[str, list[tuple[int, float]]] = defaultdict(list)
    for row in corpus:
        cid = int(row["chunk_index"])
        for token, weight in row["lexical_weights"].items():
            index[str(token)].append((cid, float(weight)))
    return index


def search_sparse(
    *,
    query_weights: dict[str, float],
    corpus: list[dict[str, Any]],
    index: dict[str, list[tuple[int, float]]],
    top_k: int,
) -> list[dict[str, Any]]:
    scores: dict[int, float] = defaultdict(float)
    for token, q_weight in query_weights.items():
        for chunk_index, d_weight in index.get(token, []):
            scores[chunk_index] += q_weight * d_weight
    by_id = {int(row["chunk_index"]): row for row in corpus}
    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))[:top_k]
    hits: list[dict[str, Any]] = []
    for rank, (chunk_index, score) in enumerate(ranked, start=1):
        row = by_id[chunk_index]
        hits.append(
            {
                "rank": rank,
                "book_id": row["book_id"],
                "chunk_index": chunk_index,
                "page": row["page"],
                "text": row["text"],
                "sparse_score": float(score),
            }
        )
    return hits


def reciprocal_rank_fusion(
    rankings: list[list[int]],
    *,
    rrf_k: int = 60,
    top_k: int = 10,
) -> list[dict[str, Any]]:
    scores: dict[int, float] = defaultdict(float)
    sources: dict[int, dict[str, int | None]] = {}
    for list_i, ranking in enumerate(rankings):
        label = "dense" if list_i == 0 else "sparse"
        for rank, chunk_index in enumerate(ranking, start=1):
            scores[chunk_index] += 1.0 / (rrf_k + rank)
            rec = sources.setdefault(chunk_index, {"dense_rank": None, "sparse_rank": None})
            rec[f"{label}_rank"] = rank
    fused = sorted(scores.items(), key=lambda item: (-item[1], item[0]))[:top_k]
    out: list[dict[str, Any]] = []
    for rank, (chunk_index, score) in enumerate(fused, start=1):
        rec = sources[chunk_index]
        out.append(
            {
                "rank": rank,
                "chunk_index": chunk_index,
                "rrf_score": float(score),
                "dense_rank": rec["dense_rank"],
                "sparse_rank": rec["sparse_rank"],
            }
        )
    return out
