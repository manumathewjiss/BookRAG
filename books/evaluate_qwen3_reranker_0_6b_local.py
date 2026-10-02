"""
Local Qwen3-Reranker-0.6B over saved BGE-M3 dense+sparse candidates.

Does not re-embed, re-chunk, touch the database, or overwrite prior result files.
Gold labels are used only after scoring, never as model input.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import resource
import subprocess
import sys
import time
from pathlib import Path

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

from evaluate_retrieval_stage3 import first_gold_rank, hit_at, mrr_from_rank, preview

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "outputs"
MODEL_ID = "Qwen/Qwen3-Reranker-0.6B"
FINAL_K = 10
# Official default instruction from the model card.
INSTRUCTION = "Given a web search query, retrieve relevant passages that answer the query"
PREFIX = (
    '<|im_start|>system\nJudge whether the Document meets the requirements based on the Query '
    'and the Instruct provided. Note that the answer can only be "yes" or "no".<|im_end|>\n'
    "<|im_start|>user\n"
)
SUFFIX = "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"
MAX_LENGTH = 2048
DIRECTORY_MARKERS = (
    "p.o. box",
    "pamho.net",
    "hare krishna land",
    "cairo rd",
    "iskcon.",
    "kisumu, kenya",
    "ujjain, mp",
    "lome, togo",
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_head() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT.parent,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return None


def rss_bytes() -> int:
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)


def disk_free_gb(path: Path) -> float:
    st = os.statvfs(path)
    return (st.f_bavail * st.f_frsize) / (1024**3)


def looks_like_directory(text: str) -> bool:
    low = text.lower()
    return any(m in low for m in DIRECTORY_MARKERS)


def choose_device(requested: str) -> tuple[str, torch.dtype, str]:
    if requested == "cpu":
        return "cpu", torch.float32, "requested cpu"
    if requested == "mps" or requested == "auto":
        if torch.backends.mps.is_available() and torch.backends.mps.is_built():
            return "mps", torch.float16, "Apple MPS available"
        return "cpu", torch.float32, "MPS not available; using CPU"
    raise ValueError(f"Unknown device {requested}")


def load_chunks(path: Path) -> dict[int, dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("artifact") != "validated_chunks":
        raise ValueError(f"{path} is not a Stage 1 validated_chunks artifact.")
    return {int(c["chunk_index"]): c for c in payload["chunks"]}


def union_candidates(question: dict, chunks: dict[int, dict]) -> list[dict]:
    by_id: dict[int, dict] = {}
    for h in question.get("dense_candidates") or []:
        cid = int(h["chunk_index"])
        rec = by_id.setdefault(
            cid,
            {"chunk_index": cid, "dense_rank": None, "sparse_rank": None, "dense_similarity": None, "sparse_score": None},
        )
        rec["dense_rank"] = int(h["rank"])
        rec["dense_similarity"] = h.get("similarity")
    for h in question.get("sparse_candidates") or []:
        cid = int(h["chunk_index"])
        rec = by_id.setdefault(
            cid,
            {"chunk_index": cid, "dense_rank": None, "sparse_rank": None, "dense_similarity": None, "sparse_score": None},
        )
        rec["sparse_rank"] = int(h["rank"])
        rec["sparse_score"] = h.get("sparse_score")
    out = []
    for cid, rec in sorted(by_id.items()):
        if cid not in chunks:
            raise RuntimeError(f"chunk_index {cid} missing from Stage 1 file")
        rec["page"] = chunks[cid].get("page")
        rec["text"] = chunks[cid]["text"]
        rec["is_address_directory"] = looks_like_directory(rec["text"])
        out.append(rec)
    return out


def format_pair(query: str, doc: str) -> str:
    return f"<Instruct>: {INSTRUCTION}\n<Query>: {query}\n<Document>: {doc}"


class Qwen3Reranker:
    def __init__(self, model_id: str, device: str, dtype: torch.dtype, max_length: int = MAX_LENGTH):
        self.model_id = model_id
        self.device = device
        self.dtype = dtype
        self.max_length = max_length
        self.tokenizer = AutoTokenizer.from_pretrained(model_id, padding_side="left")
        self.model = AutoModelForCausalLM.from_pretrained(model_id, dtype=dtype).eval()
        self.model.to(device)
        self.token_false_id = self.tokenizer.convert_tokens_to_ids("no")
        self.token_true_id = self.tokenizer.convert_tokens_to_ids("yes")
        self.prefix_tokens = self.tokenizer.encode(PREFIX, add_special_tokens=False)
        self.suffix_tokens = self.tokenizer.encode(SUFFIX, add_special_tokens=False)
        self.revision = getattr(self.model.config, "_name_or_path", model_id)

    def score_pairs(self, query: str, documents: list[str], batch_size: int) -> list[float]:
        scores: list[float] = []
        overhead = len(self.prefix_tokens) + len(self.suffix_tokens)
        body_max = self.max_length - overhead
        for start in range(0, len(documents), batch_size):
            batch_docs = documents[start : start + batch_size]
            pairs = [format_pair(query, doc) for doc in batch_docs]
            encoded = self.tokenizer(
                pairs,
                padding=False,
                truncation="longest_first",
                return_attention_mask=False,
                max_length=body_max,
            )
            for i, ids in enumerate(encoded["input_ids"]):
                encoded["input_ids"][i] = self.prefix_tokens + ids + self.suffix_tokens
            padded = self.tokenizer.pad(
                encoded,
                padding=True,
                return_tensors="pt",
                max_length=self.max_length,
            )
            padded = {k: v.to(self.device) for k, v in padded.items()}
            with torch.inference_mode():
                logits = self.model(**padded).logits[:, -1, :]
                true_v = logits[:, self.token_true_id]
                false_v = logits[:, self.token_false_id]
                stacked = torch.stack([false_v, true_v], dim=1)
                log_probs = torch.nn.functional.log_softmax(stacked, dim=1)
                batch_scores = log_probs[:, 1].exp().detach().cpu().tolist()
            scores.extend(float(s) for s in batch_scores)
            if self.device == "mps":
                torch.mps.empty_cache()
        return scores


def metrics_from_ranks(ranks: list[int | None]) -> dict:
    n = len(ranks)
    n1 = sum(1 for r in ranks if hit_at(r, 1))
    n5 = sum(1 for r in ranks if hit_at(r, 5))
    n10 = sum(1 for r in ranks if hit_at(r, 10))
    return {
        "n_questions": n,
        "n_hit@1": n1,
        "n_hit@5": n5,
        "n_hit@10": n10,
        "recall_hit@1": n1 / n if n else 0.0,
        "recall_hit@5": n5 / n if n else 0.0,
        "recall_hit@10": n10 / n if n else 0.0,
        "mrr@10": sum(mrr_from_rank(r, 10) for r in ranks) / n if n else 0.0,
        "n_misses_top10": n - n10,
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Rerank saved hybrid candidates with local Qwen3-Reranker-0.6B.")
    p.add_argument("--book-id", required=True)
    p.add_argument("--hybrid", type=Path, required=True)
    p.add_argument("--chunks", type=Path, required=True)
    p.add_argument("--eval", type=Path, required=True)
    p.add_argument("--results", type=Path, required=True)
    p.add_argument("--summary", type=Path, required=True)
    p.add_argument("--device", default="auto", choices=["auto", "mps", "cpu"])
    p.add_argument("--batch-size", type=int, default=2)
    p.add_argument("--ids", nargs="*", help="Optional question ids for a smoke test.")
    p.add_argument("--min-free-gb", type=float, default=3.0)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    free = disk_free_gb(Path.home())
    print(f"Disk free: {free:.1f} GiB")
    if free < args.min_free_gb:
        print(f"Refusing to download: only {free:.1f} GiB free (need {args.min_free_gb}).")
        return 2

    from huggingface_hub import model_info

    info = model_info(MODEL_ID)
    revision = info.sha
    print(f"Model {MODEL_ID} revision={revision}")

    device, dtype, reason = choose_device(args.device)
    print(f"Device={device} dtype={dtype} ({reason})")
    reranker = Qwen3Reranker(MODEL_ID, device=device, dtype=dtype)

    hybrid = json.loads(args.hybrid.read_text(encoding="utf-8"))
    chunks = load_chunks(args.chunks)
    questions = hybrid["questions"]
    if args.ids:
        wanted = set(args.ids)
        questions = [q for q in questions if q["id"] in wanted]
        if len(questions) != len(wanted):
            found = {q["id"] for q in questions}
            raise RuntimeError(f"Missing ids: {wanted - found}")

    results = []
    ranks: list[int | None] = []
    t0 = time.perf_counter()
    score_seconds = 0.0
    n_pairs = 0
    for q in questions:
        gold = set(int(i) for i in q["gold_chunk_indexes"])
        cands = union_candidates(q, chunks)
        gold_in_list = sorted(gold & {c["chunk_index"] for c in cands})
        n_pairs += len(cands)
        ts = time.perf_counter()
        scores = reranker.score_pairs(q["question"], [c["text"] for c in cands], args.batch_size)
        score_seconds += time.perf_counter() - ts
        for cand, score in zip(cands, scores):
            cand["rerank_score"] = score
        ranked = sorted(cands, key=lambda c: (-c["rerank_score"], c["chunk_index"]))
        for i, cand in enumerate(ranked, start=1):
            cand["rerank_rank"] = i
        top10 = ranked[:FINAL_K]
        rank = first_gold_rank([c["chunk_index"] for c in top10], gold)
        ranks.append(rank)
        results.append(
            {
                "id": q["id"],
                "question": q["question"],
                "book_id": args.book_id,
                "gold_chunk_indexes": sorted(gold),
                "gold_in_candidate_list": gold_in_list,
                "n_candidates": len(cands),
                "candidates": [
                    {
                        "chunk_index": c["chunk_index"],
                        "page": c["page"],
                        "dense_rank": c["dense_rank"],
                        "sparse_rank": c["sparse_rank"],
                        "rerank_score": c["rerank_score"],
                        "rerank_rank": c["rerank_rank"],
                        "is_address_directory": c["is_address_directory"],
                        "text_preview": preview(c["text"]),
                    }
                    for c in ranked
                ],
                "retrieved": [
                    {
                        "rank": c["rerank_rank"],
                        "chunk_index": c["chunk_index"],
                        "page": c["page"],
                        "rerank_score": c["rerank_score"],
                        "dense_rank": c["dense_rank"],
                        "sparse_rank": c["sparse_rank"],
                        "is_address_directory": c["is_address_directory"],
                        "text_preview": preview(c["text"]),
                    }
                    for c in top10
                ],
                "first_gold_rank": rank,
                "hit_at_1": hit_at(rank, 1),
                "hit_at_5": hit_at(rank, 5),
                "hit_at_10": hit_at(rank, 10),
                "reciprocal_rank": mrr_from_rank(rank, 10),
            }
        )
        print(
            f"{q['id']} candidates={len(cands)} gold_in_list={bool(gold_in_list)} "
            f"rerank_gold_rank={rank} top1={top10[0]['chunk_index']} score={top10[0]['rerank_score']:.4f}"
        )

    elapsed = time.perf_counter() - t0
    mets = metrics_from_ranks(ranks)
    payload = {
        "book_id": args.book_id,
        "embedding_family": "qwen3_reranker_0_6b_local",
        "reranker_model": MODEL_ID,
        "model_revision": revision,
        "device": device,
        "dtype": str(dtype).replace("torch.", ""),
        "instruction": INSTRUCTION,
        "input_format": "official Qwen3-Reranker yes/no logits: prefix + <Instruct>/<Query>/<Document> + suffix",
        "max_length": MAX_LENGTH,
        "batch_size": args.batch_size,
        "candidate_source": "union of saved BGE-M3 dense_candidates and sparse_candidates",
        "eval_file": str(args.eval),
        "eval_sha256": sha256_file(args.eval),
        "chunks_sha256": sha256_file(args.chunks),
        "hybrid_sha256": sha256_file(args.hybrid),
        "n_questions": len(questions),
        "questions": results,
    }
    args.results.parent.mkdir(parents=True, exist_ok=True)
    args.results.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    summary = {
        "reranker_model": MODEL_ID,
        "model_revision": revision,
        "embedding_family": "qwen3_reranker_0_6b_local",
        "device": device,
        "device_reason": reason,
        "dtype": str(dtype).replace("torch.", ""),
        "instruction": INSTRUCTION,
        "book_filter": args.book_id,
        "n_pairs_scored": n_pairs,
        "processing_time_seconds": round(elapsed, 3),
        "score_seconds": round(score_seconds, 3),
        "peak_rss_bytes": rss_bytes(),
        "peak_rss_gib": round(rss_bytes() / (1024**3), 3),
        "git_head": git_head(),
        "eval_sha256": sha256_file(args.eval),
        "chunks_sha256": sha256_file(args.chunks),
        "hybrid_sha256": sha256_file(args.hybrid),
        "results_file": str(args.results),
        "gold_labels_given_to_model": False,
        "warnings": [],
        "errors": [],
        **mets,
    }
    args.summary.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{args.book_id} Qwen3-Reranker-0.6B {device}")
    print(f"Hit@1/5/10 {mets['n_hit@1']}/{mets['n_hit@5']}/{mets['n_hit@10']} MRR={mets['mrr@10']:.4f}")
    print(f"Time {elapsed:.1f}s pairs={n_pairs} peak_rss_GiB={summary['peak_rss_gib']}")
    print(f"Wrote {args.results}")
    print(f"Wrote {args.summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
