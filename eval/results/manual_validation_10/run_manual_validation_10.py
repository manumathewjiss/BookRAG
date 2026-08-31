#!/usr/bin/env python3
"""
One-off MANUAL retrieval validation (10 questions).

READ-ONLY: does not rebuild indexes, does not train, does not touch
production code, frozen 100-question benchmark, or prior eval results.

Uses existing indexes:
  A. Sanskrit-only FAISS  (Documents workspace production index)
  B. English-only FAISS   (Projects clone — missing in Documents workspace)
  C. Sanskrit+English FAISS (Projects clone — missing in Documents workspace)

All three were built with intfloat/multilingual-e5-large,
HuggingFaceEmbeddings(model_name=...) only: no E5 prefixes, no
normalize_embeddings, FAISS IndexFlatL2.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")
os.environ.setdefault("TORCH_DEVICE_BACKEND_AUTOLOAD", "0")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("VECLIB_MAXIMUM_THREADS", "1")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")
os.environ.setdefault("JOBLIB_MULTIPROCESSING", "0")
os.environ.setdefault("LOKY_MAX_CPU_COUNT", "1")

import importlib.metadata as _importlib_metadata

_importlib_metadata.packages_distributions = lambda: {}  # type: ignore[method-assign]

print("manual-10: process start", flush=True)

# This file lives at eval/results/manual_validation_10/run_*.py
ROOT = Path(__file__).resolve().parents[3]
OUT_DIR = Path(__file__).resolve().parent
print("manual-10: ROOT", ROOT, flush=True)
CSV_PATH = ROOT / "res" / "combined.csv"
PROJECTS_CLONE = Path("/Users/manumathewjiss/Projects/Pramod-Gupta-Project")

SANSKRIT_INDEX = ROOT / "sanskrit_faiss_index_itihasa"
ENGLISH_INDEX = PROJECTS_CLONE / "faiss_index_itihasa_english_only"
COMBINED_INDEX = PROJECTS_CLONE / "sanskrit_english_faiss_index_itihasa"

EVAL_K = 10
EXPECTED_NTOTAL = 93030

# gold_row_index is the 0-based pandas/csv.DictReader index of res/combined.csv
# (first data row = 0). It is NOT the file line number and NOT the shloka number.
# file_line = gold_row_index + 2 (header is line 1).
#
# 2026-08-27 correction: mv10_03 18->19 and mv10_04 19->20. Original labels
# pointed at the previous CSV row (editor line-number off-by-one). Validation
# now requires gold_english to contain support tokens for expected_answer.
FROZEN_QUESTIONS: List[Dict[str, Any]] = [
    {
        "question_id": "mv10_01",
        "question": "Which sage did Valmiki ask about a man of outstanding virtue?",
        "expected_answer": "Narada",
        "gold_row_index": 0,
        "category": "person",
        "gold_must_contain_any": ["nārada", "narada", "nărada"],
        "short_reason_why_this_is_gold": "This opening verse names Valmiki asking Narada; the next verses are Valmiki's questions, not the addressee.",
    },
    {
        "question_id": "mv10_02",
        "question": "After meeting the Nishada king Guha, where did Rama dismiss his charioteer?",
        "expected_answer": "On the banks of the Ganges at Srigaverapura",
        "gold_row_index": 24,
        "category": "place",
        "gold_must_contain_any": ["srigaverapura"],
        "short_reason_why_this_is_gold": "This verse uniquely names Srigaverapura on the Ganges as the place where Rama, with Guha, Lakshmana, and Sita, dismissed the charioteer.",
    },
    {
        "question_id": "mv10_03",
        "question": "When Kaikeyi claimed the two boons she had been promised, what two things did she ask for?",
        "expected_answer": "The exile of Rama and the installation of Bharata",
        "gold_row_index": 19,
        "category": "event",
        "gold_must_contain_any": ["kaikey"],
        "gold_must_contain_all": ["exile", "bharata"],
        "short_reason_why_this_is_gold": "This verse states Kaikeyi asked for those two boons: Rama's exile and Bharata's installation.",
    },
    {
        "question_id": "mv10_04",
        "question": "Why did king Dasaratha banish his son Rama?",
        "expected_answer": "Because he was bound by duty to keep his promise",
        "gold_row_index": 20,
        "category": "reason",
        "gold_must_contain_all": ["promise", "banish"],
        "short_reason_why_this_is_gold": "This verse says Dasaratha banished Rama because he was bound by duty in consequence of his promise.",
    },
    {
        "question_id": "mv10_05",
        "question": "After Dasaratha died, did Bharata accept the throne when Vasistha and the other Brahmanas pressed him to rule?",
        "expected_answer": "No. He refused the kingdom and went to the forest to seek Rama.",
        "gold_row_index": 27,
        "category": "character",
        "gold_must_contain_any": ["bharata"],
        "gold_must_contain_all": ["did not wish for dominion"],
        "short_reason_why_this_is_gold": "This verse says Bharata, though pressed by Brahmanas headed by Vasistha, did not wish for dominion and went to the forest to propitiate Rama.",
    },
    {
        "question_id": "mv10_06",
        "question": "When the Ocean appeared and advised them, who built the causeway across the sea?",
        "expected_answer": "Nala",
        "gold_row_index": 64,
        "category": "factual",
        "gold_must_contain_any": ["nala"],
        "short_reason_why_this_is_gold": "This verse says that, agreeably to the Ocean's advice, Nala constructed the bridge. Other verses mention monkeys or Rama in related scenes but do not give this Ocean-advice + Nala pairing.",
    },
    {
        "question_id": "mv10_07",
        "question": "Who lured Rama far from the ashram by taking the form of a golden deer?",
        "expected_answer": "Marica",
        "gold_row_index": 6935,
        "category": "event",
        "gold_must_contain_any": ["mārica", "marica", "mārīca"],
        "gold_must_contain_all": ["golden deer"],
        "short_reason_why_this_is_gold": "Rama states that Marica became a golden deer, allured him far, then turned back into a rakshasa when struck.",
    },
    {
        "question_id": "mv10_08",
        "question": "What did Ekalavya cut off and give to Drona as the teacher's fee?",
        "expected_answer": "His right thumb",
        "gold_row_index": 23857,
        "category": "factual",
        "gold_must_contain_all": ["right thumb"],
        "short_reason_why_this_is_gold": "This verse says Ekalavya cut off his right thumb and gave it to Drona after Drona demanded it.",
    },
    {
        "question_id": "mv10_09",
        "question": "How far did Hanuman say he leaped across the ocean to carry out Rama's work?",
        "expected_answer": "One hundred yojanas",
        "gold_row_index": 33766,
        "category": "factual",
        "gold_must_contain_all": ["hundred yojanas"],
        "short_reason_why_this_is_gold": "Hanuman, speaking to Bhima, says he suddenly leaped over the ocean extending one hundred yojanas to accomplish Rama's work.",
    },
    {
        "question_id": "mv10_10",
        "question": "In Krishna's teaching to Arjuna, what does he say a person should be concerned with, and never with?",
        "expected_answer": "Concerned only with actions, never with their fruits",
        "gold_row_index": 48027,
        "category": "teaching",
        "gold_must_contain_all": ["only with actions", "never with their fruits"],
        "short_reason_why_this_is_gold": "This Gita verse states: your concern is only with actions, never with their fruits. Nearby verses discuss related ideas but this is the direct statement of that rule.",
    },
]


print("manual-10: importing torch (no pandas)", flush=True)
try:
    import torch

    torch.backends.mps.is_available = lambda: False  # type: ignore[method-assign]
    torch.backends.mps.is_built = lambda: False  # type: ignore[method-assign]
    print("manual-10: torch ok", torch.__version__, flush=True)
except Exception as err:
    print("manual-10: torch skip", err, flush=True)

print("manual-10: importing langchain FAISS + HuggingFaceEmbeddings", flush=True)
from langchain_community.embeddings import HuggingFaceEmbeddings  # noqa: E402
from langchain_community.vectorstores import FAISS  # noqa: E402

print("manual-10: langchain ok", flush=True)

EMBEDDINGS_MODEL = "intfloat/multilingual-e5-large"


def index_exists(path: Path) -> bool:
    return path.is_dir() and (path / "index.faiss").is_file() and (path / "index.pkl").is_file()


def file_fingerprint(path: Path) -> Dict[str, Any]:
    st = path.stat()
    h = hashlib.sha256()
    with path.open("rb") as f:
        h.update(f.read(1024 * 1024))
    return {
        "path": str(path),
        "size": st.st_size,
        "mtime": st.st_mtime,
        "mtime_human": time.ctime(st.st_mtime),
        "sha256_first_1mb": h.hexdigest(),
    }


def load_corpus(path: Path) -> Dict[int, Dict[str, str]]:
    print(f"Loading corpus {path}", flush=True)
    out: Dict[int, Dict[str, str]] = {}
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            out[i] = {
                "book": str(row.get("book") or ""),
                "chapter": str(row.get("chapter") or ""),
                "shloka": str(row.get("shloka") or ""),
                "sn": str(row.get("sn") or "").strip(),
                "en": str(row.get("en") or "").strip(),
            }
    print(f"Corpus rows: {len(out)}", flush=True)
    return out


def ngrams(text: str, n: int) -> List[str]:
    toks = [t for t in "".join(c.lower() if c.isalnum() or c.isspace() else " " for c in text).split() if t]
    if len(toks) < n:
        return []
    return [" ".join(toks[i : i + n]) for i in range(len(toks) - n + 1)]


def _norm(text: str) -> str:
    return " ".join((text or "").lower().split())


def assert_gold_supports_expected_answer(qid: str, spec: Dict[str, Any], gold_english: str) -> List[str]:
    """Fail closed if the selected CSV row does not contain the expected answer."""
    en = _norm(gold_english)
    errs: List[str] = []
    any_toks = spec.get("gold_must_contain_any") or []
    all_toks = spec.get("gold_must_contain_all") or []
    if any_toks and not any(_norm(t) in en for t in any_toks):
        errs.append(
            f"{qid}: gold_english does not contain any of {any_toks!r}; "
            "gold_row_index does not support expected_answer"
        )
    for tok in all_toks:
        if _norm(tok) not in en:
            errs.append(
                f"{qid}: gold_english missing required support token {tok!r}; "
                "gold_row_index does not support expected_answer"
            )
    if not any_toks and not all_toks:
        errs.append(f"{qid}: missing gold_must_contain_* tokens in generator spec")
    return errs


def validate_and_freeze(corpus: Dict[int, Dict[str, str]]) -> Dict[str, Any]:
    qs = FROZEN_QUESTIONS
    errors: List[str] = []
    if len(qs) != 10:
        errors.append(f"expected 10 questions, got {len(qs)}")
    texts = [q["question"].strip() for q in qs]
    ids = [q["question_id"] for q in qs]
    golds = [int(q["gold_row_index"]) for q in qs]
    if len(set(texts)) != len(texts):
        errors.append("duplicate questions")
    if len(set(ids)) != len(ids):
        errors.append("duplicate question_id")
    if len(set(golds)) != len(golds):
        errors.append("duplicate gold_row_index")
    filled: List[Dict[str, Any]] = []
    for q in qs:
        rid = int(q["gold_row_index"])
        if rid not in corpus:
            errors.append(f"{q['question_id']}: gold_row_index {rid} missing from combined.csv")
            continue
        row = corpus[rid]
        qtext = q["question"].strip()
        en = row["en"]
        sn = row["sn"]
        if not qtext or not en or not sn:
            errors.append(f"{q['question_id']}: empty question or gold verse")
        if qtext.lower() == en.lower():
            errors.append(f"{q['question_id']}: question is an exact copy of the English verse")
        shared6 = set(ngrams(qtext, 6)) & set(ngrams(en, 6))
        if shared6:
            errors.append(f"{q['question_id']}: shares 6-gram with gold English: {sorted(shared6)[:3]}")
        errors.extend(assert_gold_supports_expected_answer(q["question_id"], q, en))
        rec = {
            "question_id": q["question_id"],
            "question": qtext,
            "expected_answer": q["expected_answer"],
            "gold_row_index": rid,
            "book": row["book"],
            "chapter": row["chapter"],
            "shloka": row["shloka"],
            "gold_sanskrit": sn,
            "gold_english": en,
            "short_reason_why_this_is_gold": q["short_reason_why_this_is_gold"],
            "category": q["category"],
        }
        filled.append(rec)
    payload = {
        "name": "manual_validation_10_questions",
        "purpose": (
            "Small human-readable retrieval check for manager review. "
            "NOT a replacement for the frozen 100-question Recall/MRR benchmark. "
            "Questions and gold labels were frozen BEFORE retrieval."
        ),
        "frozen": True,
        "n": len(filled),
        "corpus": str(CSV_PATH),
        "gold_id_field": "row_index",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "label_correction": {
            "date_utc": "2026-08-27",
            "reason": (
                "Objective CSV labeling error, not a retrieval-driven relabel. "
                "gold_row_index was assigned from the previous combined.csv row "
                "(editor/file line number treated as if it were pandas row_index). "
                "gold_row_index is 0-based DictReader index; file_line = row_index + 2."
            ),
            "changes": [
                {
                    "question_id": "mv10_03",
                    "old_gold_row_index": 18,
                    "corrected_gold_row_index": 19,
                    "csv_proof": (
                        "Row 18 is Dasaratha wishing to install Rama. "
                        "Row 19 names Kaikeyi asking for Rama's exile and Bharata's installation."
                    ),
                },
                {
                    "question_id": "mv10_04",
                    "old_gold_row_index": 19,
                    "corrected_gold_row_index": 20,
                    "csv_proof": (
                        "Row 19 is Kaikeyi's two boons. "
                        "Row 20 says Dasaratha, bound by duty from his promise, banished Rama."
                    ),
                },
            ],
            "other_eight_questions": "verified against combined.csv; no gold_row_index change",
        },
        "validation_errors": errors,
        "questions": filled,
        "scientific_rule": (
            "Do not change a question or its gold after seeing retrieval results. "
            "If a question looks ambiguous after retrieval, FLAG it for human review. "
            "Exception: correct an objective combined.csv labeling/data-generation error "
            "when the frozen gold row clearly does not support the predefined expected answer."
        ),
    }
    if errors:
        raise RuntimeError("Question validation failed:\n" + "\n".join(errors))
    print(
        "OK  10 unique questions, unique gold rows, gold rows exist, "
        "expected_answer supported by gold_english, not exact verse copies",
        flush=True,
    )
    return payload


def row_index_from_doc(doc) -> Optional[int]:
    raw = doc.metadata.get("row_index") if getattr(doc, "metadata", None) else None
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def sn_en_from_doc(doc, corpus: Dict[int, Dict[str, str]]) -> Tuple[str, str]:
    meta = getattr(doc, "metadata", {}) or {}
    rid = row_index_from_doc(doc)
    sn = str(meta.get("sanskrit_text") or "").strip()
    en = str(meta.get("english_text") or "").strip()
    pc = str(getattr(doc, "page_content", "") or "")
    if "\n\n" in pc and (not sn or not en):
        left, right = pc.split("\n\n", 1)
        sn = sn or left.strip()
        en = en or right.strip()
    if rid is not None and rid in corpus:
        if not sn:
            sn = corpus[rid]["sn"]
        if not en:
            en = corpus[rid]["en"]
    if not sn and pc:
        sn = pc
    if not en and pc and rid is None:
        en = pc
    return sn, en


def retrieve_system(name: str, store, questions: List[Dict[str, Any]], corpus: Dict[int, Dict[str, str]]) -> Dict[str, Any]:
    print(f"Retrieving Top {EVAL_K} on {name}...", flush=True)
    per_q: List[Dict[str, Any]] = []
    t0 = time.time()
    for i, q in enumerate(questions, start=1):
        hits = store.similarity_search_with_score(q["question"], k=EVAL_K)
        gold = int(q["gold_row_index"])
        rank = None
        hit_rows: List[Dict[str, Any]] = []
        for r, (doc, score) in enumerate(hits, start=1):
            rid = row_index_from_doc(doc)
            if rid == gold and rank is None:
                rank = r
            sn, en = sn_en_from_doc(doc, corpus)
            hit_rows.append(
                {
                    "rank": r,
                    "row_index": rid,
                    "score_l2": float(score) if score is not None else None,
                    "sanskrit": sn,
                    "english": en,
                    "book": str((doc.metadata or {}).get("book", "")),
                    "chapter": str((doc.metadata or {}).get("chapter", "")),
                    "shloka_num": str((doc.metadata or {}).get("shloka_num", "")),
                }
            )
        top1 = hit_rows[0] if hit_rows else {}
        per_q.append(
            {
                "question_id": q["question_id"],
                "question": q["question"],
                "gold_row_index": gold,
                "gold_rank": rank,
                "top1_row_index": top1.get("row_index"),
                "top1_sanskrit": top1.get("sanskrit", ""),
                "top1_english": top1.get("english", ""),
                "top5_row_indices": [h["row_index"] for h in hit_rows[:5]],
                "top10": hit_rows,
            }
        )
        print(
            f"  {name} {i}/10 {q['question_id']} gold_rank={rank} top1={top1.get('row_index')} "
            f"elapsed={time.time() - t0:.1f}s",
            flush=True,
        )
    return {"system": name, "n": len(per_q), "elapsed_sec": time.time() - t0, "per_question": per_q}


def csv_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return ",".join("" if x is None else str(x) for x in value)
    return str(value)


def write_comparison_csv(path: Path, questions: List[Dict[str, Any]], by_sys: Dict[str, Dict[str, Any]]) -> None:
    def qmap(sys: str) -> Dict[str, Any]:
        return {row["question_id"]: row for row in by_sys[sys]["per_question"]}

    skt = qmap("sanskrit_only")
    eng = qmap("english_only")
    comb = qmap("sanskrit_english")
    fields = [
        "question_id",
        "question",
        "expected_answer",
        "gold_row_index",
        "Sanskrit_only_gold_rank",
        "Sanskrit_only_top1_row_index",
        "Sanskrit_only_top1_sanskrit",
        "Sanskrit_only_top1_english",
        "Sanskrit_only_top5_row_indices",
        "English_only_gold_rank",
        "English_only_top1_row_index",
        "English_only_top1_sanskrit",
        "English_only_top1_english",
        "English_only_top5_row_indices",
        "Sanskrit_English_gold_rank",
        "Sanskrit_English_top1_row_index",
        "Sanskrit_English_top1_sanskrit",
        "Sanskrit_English_top1_english",
        "Sanskrit_English_top5_row_indices",
        "manual_sanskrit_rating",
        "manual_english_rating",
        "manual_combined_rating",
        "manual_notes",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for q in questions:
            qid = q["question_id"]
            s, e, c = skt[qid], eng[qid], comb[qid]
            w.writerow(
                {
                    "question_id": qid,
                    "question": q["question"],
                    "expected_answer": q["expected_answer"],
                    "gold_row_index": q["gold_row_index"],
                    "Sanskrit_only_gold_rank": s["gold_rank"] if s["gold_rank"] is not None else "",
                    "Sanskrit_only_top1_row_index": s["top1_row_index"] if s["top1_row_index"] is not None else "",
                    "Sanskrit_only_top1_sanskrit": s["top1_sanskrit"],
                    "Sanskrit_only_top1_english": s["top1_english"],
                    "Sanskrit_only_top5_row_indices": csv_cell(s["top5_row_indices"]),
                    "English_only_gold_rank": e["gold_rank"] if e["gold_rank"] is not None else "",
                    "English_only_top1_row_index": e["top1_row_index"] if e["top1_row_index"] is not None else "",
                    "English_only_top1_sanskrit": e["top1_sanskrit"],
                    "English_only_top1_english": e["top1_english"],
                    "English_only_top5_row_indices": csv_cell(e["top5_row_indices"]),
                    "Sanskrit_English_gold_rank": c["gold_rank"] if c["gold_rank"] is not None else "",
                    "Sanskrit_English_top1_row_index": c["top1_row_index"] if c["top1_row_index"] is not None else "",
                    "Sanskrit_English_top1_sanskrit": c["top1_sanskrit"],
                    "Sanskrit_English_top1_english": c["top1_english"],
                    "Sanskrit_English_top5_row_indices": csv_cell(c["top5_row_indices"]),
                    "manual_sanskrit_rating": "",
                    "manual_english_rating": "",
                    "manual_combined_rating": "",
                    "manual_notes": "",
                }
            )


def clip(text: str, n: int = 500) -> str:
    text = " ".join((text or "").split())
    if len(text) <= n:
        return text
    return text[: n - 1] + "…"


def write_review_md(
    path: Path,
    questions: List[Dict[str, Any]],
    by_sys: Dict[str, Any],
    indexes: Dict[str, Any],
    flags: List[str],
) -> None:
    def qmap(sys: str) -> Dict[str, Any]:
        return {row["question_id"]: row for row in by_sys[sys]["per_question"]}

    skt, eng, comb = qmap("sanskrit_only"), qmap("english_only"), qmap("sanskrit_english")
    lines: List[str] = []
    lines.append("# Manual retrieval validation (10 questions)")
    lines.append("")
    lines.append("This is a **small human review** requested for manager discussion.")
    lines.append("It is **not** a replacement for the frozen 100-question Recall/MRR benchmark.")
    lines.append("Do **not** declare a winner from these 10 questions.")
    lines.append("")
    lines.append(
        "Label correction (2026-08-27): mv10_03 gold 18→19 and mv10_04 gold 19→20 "
        "because `combined.csv` showed the original rows did not contain the expected answers. "
        "The other eight gold rows were unchanged. Questions were not rewritten."
    )
    lines.append("")
    lines.append("Suggested ratings: `Correct` / `Partially Correct` / `Wrong`")
    lines.append("")
    lines.append("## Indexes used (existing, not rebuilt)")
    lines.append("")
    lines.append(f"- Sanskrit-only: `{indexes['sanskrit_only']['path']}`")
    lines.append(f"- English-only: `{indexes['english_only']['path']}`")
    lines.append(f"- Sanskrit + English: `{indexes['sanskrit_english']['path']}`")
    lines.append("")
    lines.append("Shared encoder config (all three existing indexes): `intfloat/multilingual-e5-large`,")
    lines.append("no `query:`/`passage:` prefixes, no embedding normalization, FAISS L2 / IndexFlatL2.")
    lines.append("")
    if flags:
        lines.append("## Flags for human review")
        lines.append("")
        for f in flags:
            lines.append(f"- {f}")
        lines.append("")
    for q in questions:
        qid = q["question_id"]
        s, e, c = skt[qid], eng[qid], comb[qid]
        lines.append("---")
        lines.append("")
        lines.append(f"## {qid}")
        lines.append("")
        lines.append(f"QUESTION: {q['question']}")
        lines.append("")
        lines.append(f"EXPECTED ANSWER: {q['expected_answer']}")
        lines.append("")
        lines.append(
            f"GOLD VERSE: row {q['gold_row_index']} | {q['book']} chapter {q['chapter']} shloka {q['shloka']}"
        )
        lines.append("")
        lines.append(q["gold_english"])
        lines.append("")
        lines.append("SANSKRIT-ONLY:")
        lines.append(f"Top 1 retrieved English translation: {clip(s['top1_english'])}")
        lines.append(f"Gold rank: {s['gold_rank'] if s['gold_rank'] is not None else 'not in Top 10'}")
        lines.append("")
        lines.append("ENGLISH-ONLY:")
        lines.append(f"Top 1 retrieved English translation: {clip(e['top1_english'])}")
        lines.append(f"Gold rank: {e['gold_rank'] if e['gold_rank'] is not None else 'not in Top 10'}")
        lines.append("")
        lines.append("SANSKRIT + ENGLISH:")
        lines.append(f"Top 1 retrieved English translation: {clip(c['top1_english'])}")
        lines.append(f"Gold rank: {c['gold_rank'] if c['gold_rank'] is not None else 'not in Top 10'}")
        lines.append("")
        lines.append("MY MANUAL VERDICT:")
        lines.append("Sanskrit: __________")
        lines.append("English: __________")
        lines.append("Sanskrit + English: __________")
        lines.append("Notes: __________")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def collect_flags(questions: List[Dict[str, Any]], by_sys: Dict[str, Any]) -> List[str]:
    """Flag suspicious cases after retrieval. Do not change gold labels."""
    flags: List[str] = []
    maps = {
        name: {row["question_id"]: row for row in payload["per_question"]}
        for name, payload in by_sys.items()
    }
    for q in questions:
        qid = q["question_id"]
        gold = int(q["gold_row_index"])
        notes = []
        for name, m in maps.items():
            row = m[qid]
            rank = row["gold_rank"]
            top1 = row["top1_row_index"]
            top5 = row["top5_row_indices"]
            if rank is None:
                notes.append(f"{name}: gold not in Top 10")
            if top1 is not None and int(top1) != gold:
                notes.append(f"{name}: Top-1 is row {top1} (not gold {gold})")
            # nearby rows in same scene
            nearby = [x for x in top5 if x is not None and abs(int(x) - gold) <= 3 and int(x) != gold]
            if nearby:
                notes.append(f"{name}: nearby rows also in Top 5: {nearby}")
        if notes:
            flags.append(f"{qid} ({q['question']}) — " + "; ".join(notes))
    # Known scientific caveats independent of ranks
    flags.append(
        "mv10_06: other corpus verses also mention building a bridge (monkeys / Rama). "
        "Gold is the verse that names Nala acting on the Ocean's advice. Do not relabel after retrieval."
    )
    flags.append(
        "mv10_10: nearby Gita verses also discuss fruits of action. "
        "Gold is the direct 'concern is only with actions, never with their fruits' statement. Do not relabel after retrieval."
    )
    flags.append(
        "mv10_09: other verses mention a hundred-yojana leap or ocean. "
        "Gold is Hanuman's first-person statement to Bhima. Do not relabel after retrieval."
    )
    return flags


def main() -> int:
    if os.environ.get("SANSKRITY_DEMO", "").strip().lower() in {"1", "true", "yes"}:
        print("ERROR: SANSKRITY_DEMO is set. Unset it.")
        return 2

    print("=" * 70, flush=True)
    print("MANUAL VALIDATION 10 — load existing indexes only", flush=True)
    print("=" * 70, flush=True)

    indexes = {
        "sanskrit_only": SANSKRIT_INDEX,
        "english_only": ENGLISH_INDEX,
        "sanskrit_english": COMBINED_INDEX,
    }
    for name, path in indexes.items():
        if not index_exists(path):
            print(f"STOP: missing existing index {name} at {path}")
            return 2

    before = {name: file_fingerprint(path / "index.faiss") for name, path in indexes.items()}
    for name, fp in before.items():
        print(f"OK  {name}: size={fp['size']} mtime={fp['mtime_human']}", flush=True)

    corpus = load_corpus(CSV_PATH)
    frozen = validate_and_freeze(corpus)
    qpath = OUT_DIR / "manual_validation_10_questions.json"
    qpath.write_text(json.dumps(frozen, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"FROZEN questions saved: {qpath}", flush=True)

    print(
        f"Embedding constructor: HuggingFaceEmbeddings(model_name={EMBEDDINGS_MODEL}) "
        "(no prefixes, no encode_kwargs normalize)",
        flush=True,
    )
    embeddings = HuggingFaceEmbeddings(model_name=EMBEDDINGS_MODEL)
    print("embeddings loaded", flush=True)

    questions = frozen["questions"]
    results: Dict[str, Any] = {}
    loaded_meta: Dict[str, Any] = {}
    for name, path in indexes.items():
        print(f"Loading existing index (read-only): {path}", flush=True)
        store = FAISS.load_local(
            folder_path=str(path),
            embeddings=embeddings,
            allow_dangerous_deserialization=True,
        )
        ntotal = int(store.index.ntotal)
        print(f"  ntotal={ntotal}", flush=True)
        if ntotal != EXPECTED_NTOTAL:
            print(f"WARN  {name} ntotal={ntotal}, expected {EXPECTED_NTOTAL}")
        loaded_meta[name] = {
            "path": str(path.resolve()),
            "ntotal": ntotal,
            "fingerprint_before": before[name],
        }
        results[name] = retrieve_system(name, store, questions, corpus)
        del store

    after = {name: file_fingerprint(path / "index.faiss") for name, path in indexes.items()}
    for name in indexes:
        if before[name] != after[name]:
            print(f"STOP: {name} index changed during this run")
            return 2
        loaded_meta[name]["fingerprint_after"] = after[name]
        loaded_meta[name]["unchanged"] = True
    print("OK  all three existing indexes unchanged", flush=True)

    flags = collect_flags(questions, results)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    detailed = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "Top-10 reproducibility dump for manual_validation_10",
        "eval_k": EVAL_K,
        "embedding_model": EMBEDDINGS_MODEL,
        "embedding_constructor": "HuggingFaceEmbeddings(model_name=...) only",
        "e5_prefixes": False,
        "normalize_embeddings": False,
        "faiss_metric": "IndexFlatL2 (default LangChain FAISS / Euclidean)",
        "indexes": loaded_meta,
        "questions_file": str(qpath),
        "all_three_runs_completed": True,
        "flags_for_human_review": flags,
        "systems": results,
    }
    dpath = OUT_DIR / f"manual_validation_10_top10_detailed_{stamp}.json"
    dpath.write_text(json.dumps(detailed, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT_DIR / "manual_validation_10_top10_detailed.json").write_text(
        json.dumps(detailed, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    cpath = OUT_DIR / "manual_validation_10_comparison.csv"
    write_comparison_csv(cpath, questions, results)
    mpath = OUT_DIR / "manual_validation_10_review.md"
    write_review_md(mpath, questions, results, loaded_meta, flags)

    print("", flush=True)
    print("DONE", flush=True)
    print(f"questions: {qpath}", flush=True)
    print(f"csv:       {cpath}", flush=True)
    print(f"review:    {mpath}", flush=True)
    print(f"top10:     {dpath}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
