"""
Separate paid smoke test: one frozen Frankenstein question → gpt-6.1-sol.

Uses saved Qwen ranks and Stage 1 passage text. Does not re-run search,
rerank, change production retrieval, or overwrite earlier result files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from evaluate_qwen3_reranker_0_6b_local import load_chunks
from local_env import load_local_env, openai_api_key_configured
from sol_answer_common import (
    MODEL,
    ORIGINAL_INSTRUCTIONS as INSTRUCTIONS,
    REASONING_EFFORT,
    SERVICE_TIER,
    estimate_usd,
    redact,
    sanitize_citations,
)

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "outputs"
N_PASSAGES = 5
QUESTION_ID = "fr_001"
QWEN_RESULTS = OUTPUT_DIR / "frankenstein_qwen3_reranker_hybrid_pool20_results.json"
CHUNKS_PATH = OUTPUT_DIR / "frankenstein_1532610843_print_stage1_chunks.json"
EVAL_PATH = OUTPUT_DIR / "frankenstein_retrieval_eval_frozen_30.json"
FREEZE_PATH = OUTPUT_DIR / "frankenstein_retrieval_eval_frozen_30.sha256.json"
OUT_PATH = OUTPUT_DIR / "frankenstein_sol_answer_smoke_fr_001.json"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="One-question gpt-6.1-sol answer smoke test.")
    p.add_argument("--question-id", default=QUESTION_ID)
    p.add_argument("--n-passages", type=int, default=N_PASSAGES)
    p.add_argument("--qwen-results", type=Path, default=QWEN_RESULTS)
    p.add_argument("--chunks", type=Path, default=CHUNKS_PATH)
    p.add_argument("--eval", type=Path, default=EVAL_PATH)
    p.add_argument("--out", type=Path, default=OUT_PATH)
    return p.parse_args()


def support_check(*, answer: str, cited_ids: list[int], sent: list[dict], gold_ids: list[int]) -> dict[str, Any]:
    sent_ids = {int(p["passage_id"]) for p in sent}
    cited_ok = [i for i in cited_ids if i in sent_ids]
    cited_unknown = [i for i in cited_ids if i not in sent_ids]
    cited_texts = [p["text"] for p in sent if int(p["passage_id"]) in set(cited_ok)]
    blob = "\n".join(cited_texts).lower()
    markers = {
        "st_petersburgh": "petersburgh" in blob or "petersburg" in blob,
        "dec_11": "dec. 11" in blob or "december 11" in blob or "dec. 11th" in blob,
        "northern_breeze": "breeze" in blob and "northern" in blob,
    }
    gold_sent = all(g in sent_ids for g in gold_ids)
    gold_cited = all(g in set(cited_ok) for g in gold_ids)
    return {
        "cited_ids_were_in_sent_passages": not cited_unknown,
        "dropped_unknown_ids": cited_unknown,
        "gold_passages_were_sent_to_sol": gold_sent,
        "gold_passages_cited_by_sol": gold_cited,
        "cited_text_contains": markers,
        "cited_text_supports_answer": gold_cited and all(markers.values()),
        "answer_nonempty": bool(answer.strip()),
    }


def main() -> int:
    args = parse_args()
    if args.n_passages < 3 or args.n_passages > 5:
        print("n-passages must be 3, 4, or 5.")
        return 2
    if args.question_id != QUESTION_ID:
        print(f"Smoke test allows only {QUESTION_ID}.")
        return 2
    if args.out.exists():
        print(f"Refusing to overwrite {args.out}")
        return 2

    loaded_from = load_local_env()
    if not openai_api_key_configured():
        print(
            "OPENAI_API_KEY is not set. Create gitignored books/.env from books/.env.example "
            "and put the BookRAG Demo project key there. Do not paste the key into chat."
        )
        if loaded_from:
            print(f"Looked in {loaded_from} (file present, key missing).")
        return 2

    freeze = json.loads(FREEZE_PATH.read_text(encoding="utf-8"))
    eval_sha = sha256_file(args.eval)
    if eval_sha != freeze["sha256"]:
        raise RuntimeError("Frozen eval hash changed; aborting.")

    qwen = json.loads(args.qwen_results.read_text(encoding="utf-8"))
    chunks = load_chunks(args.chunks)
    row = next((q for q in qwen["questions"] if q["id"] == args.question_id), None)
    if row is None:
        raise RuntimeError(f"{args.question_id} not in {args.qwen_results}")

    ranked = sorted(row["candidates"], key=lambda c: int(c["rerank_rank"]))[: args.n_passages]
    sent = []
    for c in ranked:
        cid = int(c["chunk_index"])
        rec = chunks[cid]
        page = rec.get("page")
        sent.append(
            {
                "passage_id": cid,
                "page": page,
                "qwen_rank": int(c["rerank_rank"]),
                "qwen_score": c.get("rerank_score"),
                "text": rec["text"],
            }
        )

    passage_block = "\n\n".join(
        f"[passage_id={p['passage_id']}]\n{p['text']}" for p in sent
    )
    user_msg = (
        f"Question:\n{row['question']}\n\n"
        f"Passages (use only these; cite passage_id values):\n{passage_block}"
    )

    from openai import OpenAI

    client = OpenAI()
    schema = {
        "type": "object",
        "properties": {
            "answer": {"type": "string"},
            "supporting_passage_ids": {
                "type": "array",
                "items": {"type": "integer"},
            },
            "enough_evidence": {"type": "boolean"},
            "missing_evidence": {"type": "string"},
        },
        "required": ["answer", "supporting_passage_ids", "enough_evidence", "missing_evidence"],
        "additionalProperties": False,
    }

    t0 = time.perf_counter()
    try:
        resp = client.responses.create(
            model=MODEL,
            service_tier=SERVICE_TIER,
            store=False,
            reasoning={"effort": REASONING_EFFORT},
            instructions=INSTRUCTIONS,
            input=user_msg,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "bookrag_grounded_answer",
                    "strict": True,
                    "schema": schema,
                }
            },
        )
    except Exception as exc:
        print(redact(str(exc)))
        return 1
    elapsed = time.perf_counter() - t0

    raw_text = (resp.output_text or "").strip()
    parsed = json.loads(raw_text)
    cited_model = [int(i) for i in parsed.get("supporting_passage_ids") or []]
    citation_gate = sanitize_citations(cited_model, sent)
    cited = citation_gate["accepted_passage_ids"]
    display_citations = citation_gate["display_citations"]

    usage_obj = resp.usage
    if hasattr(usage_obj, "model_dump"):
        usage = usage_obj.model_dump()
    elif isinstance(usage_obj, dict):
        usage = usage_obj
    else:
        usage = {"input_tokens": getattr(usage_obj, "input_tokens", None), "output_tokens": getattr(usage_obj, "output_tokens", None)}

    gold = [int(i) for i in row["gold_chunk_indexes"]]
    check = support_check(answer=parsed.get("answer") or "", cited_ids=cited_model, sent=sent, gold_ids=gold)

    payload = {
        "experiment": "sol_answer_smoke",
        "production_pipeline_changed": False,
        "model": MODEL,
        "api": "openai.responses",
        "service_tier_requested": SERVICE_TIER,
        "service_tier_returned": getattr(resp, "service_tier", None),
        "reasoning_effort": REASONING_EFFORT,
        "n_passages": args.n_passages,
        "question_id": args.question_id,
        "book_id": qwen.get("book_id"),
        "question": row["question"],
        "qwen_results_file": str(args.qwen_results),
        "qwen_method": qwen.get("method"),
        "eval_sha256": eval_sha,
        "eval_unchanged_since_freeze": True,
        "passages_sent": [
            {
                "passage_id": p["passage_id"],
                "page": p["page"],
                "qwen_rank": p["qwen_rank"],
                "qwen_score": p["qwen_score"],
                "text": p["text"],
            }
            for p in sent
        ],
        "sol": {
            "answer": parsed.get("answer"),
            "supporting_passage_ids": cited,
            "supporting_passage_ids_raw": cited_model,
            "enough_evidence": parsed.get("enough_evidence"),
            "missing_evidence": parsed.get("missing_evidence"),
        },
        "display_citations": display_citations,
        "rejected_citations": citation_gate["rejected_citations"],
        "citation_gate": citation_gate["note"],
        "support_check": check,
        "api_time_seconds": round(elapsed, 3),
        "usage": usage,
        "cost": estimate_usd(usage),
        "response_id": getattr(resp, "id", None),
        "env_file_loaded": bool(loaded_from),
        "openai_project_env_set": bool(os.environ.get("OPENAI_PROJECT")),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {args.out}")
    print(f"answer: {parsed.get('answer')}")
    print(f"cited_passage_ids: {cited} pages: {[c['page'] for c in display_citations]}")
    print(
        f"enough_evidence={parsed.get('enough_evidence')} "
        f"api_s={elapsed:.2f} tokens_in={usage.get('input_tokens')} "
        f"tokens_out={usage.get('output_tokens')} est_usd={payload['cost']['estimated_usd']}"
    )
    print(f"support_check.cited_text_supports_answer={check['cited_text_supports_answer']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
