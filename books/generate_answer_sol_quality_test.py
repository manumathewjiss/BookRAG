"""
Controlled multi-book Sol answer-quality test.

Uses saved Qwen ranks and frozen questions only. Does not re-run search,
rerank, change production, or overwrite earlier result files.

Do not run until the old API key is revoked and a new BookRAG Demo key
is in gitignored books/.env. Pass --confirmed-key-rotation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

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
BUDGET_USD = 2.00
STOP_USD = 1.75
N_PASSAGES = 5
OUT_PATH = OUTPUT_DIR / "sol_answer_quality_multi_book_results.json"
SUMMARY_PATH = OUTPUT_DIR / "sol_answer_quality_multi_book_summary.json"

# Frozen before any Sol answers for this test. top5 = Qwen's best 5.
# tail5 = Qwen ranks 16–20 of a question whose gold is rank 1, so the
# supplied text should not contain the answer.
CASES = [
    {
        "id": "fr_011",
        "book": "frankenstein",
        "expect_enough": True,
        "passage_set": "qwen_top5",
        "note": "Creation scene; gold should be in Qwen top 5",
    },
    {
        "id": "fr_026",
        "book": "frankenstein",
        "expect_enough": True,
        "passage_set": "qwen_top5",
        "note": "Wedding-night murder of Elizabeth; confusable with earlier threat",
    },
    {
        "id": "tp2_001",
        "book": "thinkpython",
        "expect_enough": True,
        "passage_set": "qwen_top5",
        "note": "High-level language advantages",
    },
    {
        "id": "tp2_002",
        "book": "thinkpython",
        "expect_enough": True,
        "passage_set": "qwen_top5",
        "note": "Interpreter vs compiler",
    },
    {
        "id": "pp_001",
        "book": "pride",
        "expect_enough": True,
        "passage_set": "qwen_top5",
        "note": "Opening truth universally acknowledged",
    },
    {
        "id": "pp_005",
        "book": "pride",
        "expect_enough": True,
        "passage_set": "qwen_top5",
        "note": "Should be answerable from Qwen top 5",
    },
    {
        "id": "pp_003",
        "book": "pride",
        "expect_enough": False,
        "passage_set": "qwen_top5",
        "note": "Gold never reached hybrid-20; top 5 should lack Bingley income/name",
    },
    {
        "id": "pp_021",
        "book": "pride",
        "expect_enough": False,
        "passage_set": "qwen_top5",
        "note": "Gold outside hybrid-20",
    },
    {
        "id": "pp_028",
        "book": "pride",
        "expect_enough": False,
        "passage_set": "qwen_top5",
        "note": "Gold outside hybrid-20",
    },
    {
        "id": "fr_001",
        "book": "frankenstein",
        "expect_enough": False,
        "passage_set": "qwen_tail5",
        "note": "Controlled miss: Letter I gold is Qwen #1; send ranks 16–20 instead",
    },
    {
        "id": "tp2_001_tail",
        "source_question_id": "tp2_001",
        "book": "thinkpython",
        "expect_enough": False,
        "passage_set": "qwen_tail5",
        "note": "Controlled miss: send Qwen ranks 16–20 of the portable-language question",
    },
]

BOOKS = {
    "frankenstein": {
        "qwen": OUTPUT_DIR / "frankenstein_qwen3_reranker_hybrid_pool20_results.json",
        "chunks": OUTPUT_DIR / "frankenstein_1532610843_print_stage1_chunks.json",
        "eval": OUTPUT_DIR / "frankenstein_retrieval_eval_frozen_30.json",
        "freeze": OUTPUT_DIR / "frankenstein_retrieval_eval_frozen_30.sha256.json",
    },
    "thinkpython": {
        "qwen": OUTPUT_DIR / "thinkpython_qwen3_reranker_0_6b_local_retrieval_results_30.json",
        "chunks": OUTPUT_DIR / "thinkpython_stage1_chunks.json",
        "eval": OUTPUT_DIR / "thinkpython_retrieval_eval_frozen_30.json",
        "freeze": None,
        "eval_sha256": "14a35a59d5f222d894f8e451d54e512f234dbf120736da7ecdadf861ae754889",
    },
    "pride": {
        "qwen": OUTPUT_DIR / "pride_and_prejudice_qwen3_reranker_0_6b_pool20_results.json",
        "chunks": OUTPUT_DIR / "pride_and_prejudice_stage1_chunks.json",
        "eval": OUTPUT_DIR / "pride_and_prejudice_retrieval_eval_frozen_30.json",
        "freeze": None,
        "eval_sha256": "c258063bf54a326ef35ce661bd0e16c602a940ec47ef844e0598c013fb6328fc",
    },
}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ordered_candidates(row: dict) -> list[dict]:
    cands = row.get("candidates") or []
    def key(c: dict) -> int:
        return int(c.get("rerank_rank") or c.get("rank") or 10**9)
    return sorted(cands, key=key)


def load_question(qwen: dict, question_id: str) -> dict:
    row = next((q for q in qwen["questions"] if q["id"] == question_id), None)
    if row is None:
        raise RuntimeError(f"{question_id} missing from saved Qwen results")
    return row


def select_passages(row: dict, chunks: dict[int, dict], passage_set: str) -> list[dict]:
    ordered = ordered_candidates(row)
    if passage_set == "qwen_top5":
        picked = ordered[:N_PASSAGES]
    elif passage_set == "qwen_tail5":
        if len(ordered) < 20:
            picked = ordered[-N_PASSAGES:]
        else:
            picked = ordered[15:20]
    else:
        raise ValueError(passage_set)
    sent = []
    for c in picked:
        cid = int(c["chunk_index"])
        rec = chunks[cid]
        sent.append(
            {
                "passage_id": cid,
                "page": rec.get("page"),
                "qwen_rank": int(c.get("rerank_rank") or c.get("rank")),
                "qwen_score": c.get("rerank_score"),
                "text": rec["text"],
            }
        )
    return sent


def compact_sent(sent: list[dict]) -> list[dict]:
    out = []
    for p in sent:
        text = p["text"]
        out.append(
            {
                "passage_id": p["passage_id"],
                "page": p["page"],
                "qwen_rank": p["qwen_rank"],
                "qwen_score": p["qwen_score"],
                "text_preview": text[:220].replace("\n", " "),
                "n_chars": len(text),
            }
        )
    return out


def support_check(*, answer: str, cited_ids: list[int], sent: list[dict], gold_ids: list[int], expect_enough: bool) -> dict:
    sent_ids = {int(p["passage_id"]) for p in sent}
    cited_ok = [i for i in cited_ids if i in sent_ids]
    gold_sent = bool(set(gold_ids) & sent_ids)
    gold_cited = bool(set(gold_ids) & set(cited_ok))
    cited_blob = "\n".join(p["text"] for p in sent if p["passage_id"] in set(cited_ok)).lower()
    ans = (answer or "").strip()
    guessed_without_gold = (not gold_sent) and bool(ans) and "not" not in ans.lower()[:80]
    return {
        "cited_ids_were_in_sent_passages": all(i in sent_ids for i in cited_ids),
        "gold_in_sent_passages": gold_sent,
        "gold_cited": gold_cited,
        "expect_enough": expect_enough,
        "cited_char_count": len(cited_blob),
        "answer_nonempty": bool(ans),
        "possible_guess_without_gold": guessed_without_gold,
    }


def call_sol(client, question: str, sent: list[dict]):
    passage_block = "\n\n".join(f"[passage_id={p['passage_id']}]\n{p['text']}" for p in sent)
    user_msg = f"Question:\n{question}\n\nPassages (use only these; cite passage_id values):\n{passage_block}"
    schema = {
        "type": "object",
        "properties": {
            "answer": {"type": "string"},
            "supporting_passage_ids": {"type": "array", "items": {"type": "integer"}},
            "enough_evidence": {"type": "boolean"},
            "missing_evidence": {"type": "string"},
        },
        "required": ["answer", "supporting_passage_ids", "enough_evidence", "missing_evidence"],
        "additionalProperties": False,
    }
    t0 = time.perf_counter()
    resp = client.responses.create(
        model=MODEL,
        service_tier=SERVICE_TIER,
        store=False,
        reasoning={"effort": REASONING_EFFORT},
        instructions=INSTRUCTIONS,
        input=user_msg,
        text={"format": {"type": "json_schema", "name": "bookrag_grounded_answer", "strict": True, "schema": schema}},
    )
    elapsed = time.perf_counter() - t0
    parsed = json.loads((resp.output_text or "").strip())
    usage_obj = resp.usage
    if hasattr(usage_obj, "model_dump"):
        usage = usage_obj.model_dump()
    else:
        usage = {"input_tokens": getattr(usage_obj, "input_tokens", None), "output_tokens": getattr(usage_obj, "output_tokens", None)}
    return parsed, elapsed, usage, getattr(resp, "service_tier", None), getattr(resp, "id", None)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Multi-book Sol answer quality test.")
    p.add_argument("--confirmed-key-rotation", action="store_true")
    p.add_argument("--budget-usd", type=float, default=BUDGET_USD)
    p.add_argument("--out", type=Path, default=OUT_PATH)
    p.add_argument("--summary", type=Path, default=SUMMARY_PATH)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if not args.confirmed_key_rotation:
        print("Refusing: pass --confirmed-key-rotation after the old key is revoked and the new one is in books/.env.")
        return 2
    if args.out.exists() or args.summary.exists():
        print("Refusing to overwrite existing quality-test files.")
        return 2

    loaded_from = load_local_env()
    if not openai_api_key_configured():
        print("OPENAI_API_KEY is not set in gitignored books/.env. Do not paste the key into chat.")
        return 2

    from openai import OpenAI

    client = OpenAI()
    cache: dict[str, dict] = {}
    rows = []
    spent = 0.0

    for case in CASES:
        if spent >= STOP_USD:
            print(f"Stopping before {case['id']}: spent ${spent:.4f} (stop ${STOP_USD})")
            break
        book = BOOKS[case["book"]]
        qid = case.get("source_question_id") or case["id"]
        if case["book"] not in cache:
            qwen = json.loads(book["qwen"].read_text(encoding="utf-8"))
            eval_sha = sha256_file(book["eval"])
            expected = None
            if book.get("freeze"):
                expected = json.loads(book["freeze"].read_text(encoding="utf-8"))["sha256"]
            elif book.get("eval_sha256"):
                expected = book["eval_sha256"]
            if expected and eval_sha != expected:
                raise RuntimeError(f"Frozen eval hash changed for {case['book']}")
            cache[case["book"]] = {
                "qwen": qwen,
                "chunks": load_chunks(book["chunks"]),
                "eval_sha": eval_sha,
            }
        pack = cache[case["book"]]
        row = load_question(pack["qwen"], qid if qid != "tp2_001_tail" else "tp2_001")
        sent = select_passages(row, pack["chunks"], case["passage_set"])
        gold = [int(i) for i in row["gold_chunk_indexes"]]
        try:
            parsed, elapsed, usage, tier, resp_id = call_sol(client, row["question"], sent)
        except Exception as exc:
            print(redact(str(exc)))
            break
        cost = estimate_usd(usage)
        spent += float(cost["estimated_usd"])
        cited_raw = [int(i) for i in parsed.get("supporting_passage_ids") or []]
        citation_gate = sanitize_citations(cited_raw, sent)
        cited = citation_gate["accepted_passage_ids"]
        check = support_check(
            answer=parsed.get("answer") or "",
            cited_ids=cited_raw,
            sent=sent,
            gold_ids=gold,
            expect_enough=case["expect_enough"],
        )
        enough = bool(parsed.get("enough_evidence"))
        abstained = not enough
        ok = True
        if case["expect_enough"]:
            ok = enough and check["gold_in_sent_passages"] and check["cited_ids_were_in_sent_passages"]
        else:
            ok = abstained and not check["gold_in_sent_passages"]
        rec = {
            "case_id": case["id"],
            "question_id": qid if case["id"] != "tp2_001_tail" else "tp2_001",
            "book": case["book"],
            "book_id": pack["qwen"].get("book_id"),
            "question": row["question"],
            "passage_set": case["passage_set"],
            "note": case["note"],
            "expect_enough": case["expect_enough"],
            "gold_chunk_indexes": gold,
            "passages_sent": compact_sent(sent),
            "sol": {
                "answer": parsed.get("answer"),
                "supporting_passage_ids": cited,
                "supporting_passage_ids_raw": cited_raw,
                "enough_evidence": parsed.get("enough_evidence"),
                "missing_evidence": parsed.get("missing_evidence"),
            },
            "display_citations": citation_gate["display_citations"],
            "rejected_citations": citation_gate["rejected_citations"],
            "citation_gate": citation_gate["note"],
            "support_check": check,
            "case_passed": ok,
            "api_time_seconds": round(elapsed, 3),
            "usage": usage,
            "cost": cost,
            "service_tier_returned": tier,
            "response_id": resp_id,
            "eval_sha256": pack["eval_sha"],
        }
        rows.append(rec)
        print(
            f"{case['id']} enough={enough} expect={case['expect_enough']} passed={ok} "
            f"${cost['estimated_usd']:.4f} total=${spent:.4f} {elapsed:.1f}s"
        )
        if spent >= args.budget_usd:
            print("Hit budget cap; stopping.")
            break

    payload = {
        "experiment": "sol_answer_quality_multi_book",
        "production_pipeline_changed": False,
        "model": MODEL,
        "service_tier_requested": SERVICE_TIER,
        "reasoning_effort": REASONING_EFFORT,
        "budget_usd": args.budget_usd,
        "estimated_usd_total": round(spent, 6),
        "n_cases_planned": len(CASES),
        "n_cases_run": len(rows),
        "n_passed": sum(1 for r in rows if r["case_passed"]),
        "env_file_loaded": bool(loaded_from),
        "questions": rows,
    }
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    summary = {
        "n_cases_run": len(rows),
        "n_passed": payload["n_passed"],
        "estimated_usd_total": payload["estimated_usd_total"],
        "passed_ids": [r["case_id"] for r in rows if r["case_passed"]],
        "failed_ids": [r["case_id"] for r in rows if not r["case_passed"]],
        "results_file": str(args.out),
        "production_pipeline_changed": False,
    }
    args.summary.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {args.out}")
    print(f"Wrote {args.summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
