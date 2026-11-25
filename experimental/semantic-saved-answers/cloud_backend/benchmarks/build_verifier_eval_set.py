#!/usr/bin/env python3
"""Write the labeled verifier evaluation set. Does not call any model API."""
from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parent

DEV_PEOPLE = [
    ("Ada Lovelace", "the Analytical Engine", "1843"),
    ("Marie Curie", "polonium", "1898"),
    ("Grace Hopper", "the first compiler", "1952"),
    ("Katherine Johnson", "the Mercury calculations", "1962"),
]
HELD_PEOPLE = [
    ("Hypatia", "the Alexandrian commentaries", "400"),
    ("Emmy Noether", "abstract algebra", "1921"),
    ("Sofia Kovalevskaya", "partial differential equations", "1874"),
    ("Chien-Shiung Wu", "the parity experiment", "1956"),
    ("Rosalind Franklin", "the DNA photograph", "1952"),
    ("Lise Meitner", "nuclear fission", "1938"),
    ("Dorothy Hodgkin", "the penicillin structure", "1945"),
    ("Maryam Mirzakhani", "Riemann surfaces", "2014"),
    ("Tu Youyou", "artemisinin", "1972"),
    ("Barbara McClintock", "transposable elements", "1950"),
    ("Rita Levi-Montalcini", "nerve growth factor", "1952"),
    ("Gertrude Elion", "rational drug design", "1988"),
    ("Vera Rubin", "galaxy rotation", "1970"),
    ("Jocelyn Bell Burnell", "pulsars", "1967"),
    ("Cecilia Payne", "stellar composition", "1925"),
    ("Annie Jump Cannon", "the stellar classification", "1901"),
]


def _pair(split, number, category, saved, new, answer, citations, enough, expected, critical):
    return {
        "pair_id": f"{split}-{number:03d}",
        "split": split,
        "category": category,
        "saved_question": saved,
        "new_question": new,
        "saved_answer": answer,
        "citations": citations,
        "enough_evidence": enough,
        "expected": expected,
        "critical_hard_negative": critical,
        "label_source": "human_template",
        "model_scored": False,
    }


def _cite(page, excerpt):
    return [{"passage_id": f"passage-{page}", "pdf_page": page, "excerpt": excerpt}]


def build(split, people):
    rows = []
    n = 1

    def add(**kwargs):
        nonlocal n
        rows.append(_pair(split, n, **kwargs))
        n += 1

    for name, work, year in people:
        answer = f"{name} is credited with {work}."
        excerpt = f"The chapter states that {name} is credited with {work} in {year}."
        add(category="genuine_paraphrase", saved=f"Who is credited with {work}?",
            new=f"Which person is associated with {work}?", answer=answer,
            citations=_cite(2, excerpt), enough=True, expected="REUSE_EXACT_ANSWER", critical=False)
        add(category="genuine_paraphrase", saved=f"Who is credited with {work}?",
            new=f"Name the person credited with {work}.", answer=answer,
            citations=_cite(2, excerpt), enough=True, expected="REUSE_EXACT_ANSWER", critical=False)
        add(category="genuine_paraphrase", saved=f"What is {name} credited with?",
            new=f"Which work is attributed to {name}?", answer=answer,
            citations=_cite(2, excerpt), enough=True, expected="REUSE_EXACT_ANSWER", critical=False)
        add(category="near_match_ordinal", saved=f"Who was the first person credited with {work}?",
            new=f"Who was the second person credited with {work}?",
            answer=f"{name} was the first person credited with {work}.",
            citations=_cite(3, f"{name} was the first person credited with {work}."),
            enough=True, expected="RUN_FULL_RAG", critical=True)
        add(category="near_match_intent", saved=f"Who is credited with {work}?",
            new=f"When was {work} completed?", answer=answer,
            citations=_cite(2, excerpt), enough=True, expected="RUN_FULL_RAG", critical=True)
        add(category="citation_support", saved=f"Who is credited with {work}?",
            new=f"Which person is associated with {work}?", answer=answer,
            citations=_cite(4, excerpt) + _cite(5, f"A later note repeats that {name} is credited with {work}."),
            enough=True, expected="REUSE_EXACT_ANSWER", critical=False)
        add(category="citation_gap", saved=f"In what year was {work} completed?",
            new=f"In what year was {work} completed, and in which city?",
            answer=f"The work was completed in {year}.",
            citations=_cite(6, f"The work was completed in {year}."),
            enough=True, expected="RUN_FULL_RAG", critical=True)
        add(category="entity", saved=f"Who is credited with {work}?",
            new=f"Who is credited with a different discovery than {work}?",
            answer=answer, citations=_cite(2, excerpt), enough=True,
            expected="RUN_FULL_RAG", critical=True)
        add(category="date", saved=f"In what year was {work} completed?",
            new=f"Was {work} completed in {int(year) + 10}?",
            answer=f"The work was completed in {year}.",
            citations=_cite(6, f"The work was completed in {year}."),
            enough=True, expected="RUN_FULL_RAG", critical=True)
        add(category="quantity", saved=f"How many discoveries does the chapter attribute to {name}?",
            new=f"How many discoveries does the chapter attribute to someone other than {name}?",
            answer=f"The chapter attributes one discovery to {name}.",
            citations=_cite(7, f"The chapter attributes one discovery to {name}."),
            enough=True, expected="RUN_FULL_RAG", critical=True)
        add(category="negation", saved=f"Who is credited with {work}?",
            new=f"Who is not credited with {work}?", answer=answer,
            citations=_cite(2, excerpt), enough=True, expected="RUN_FULL_RAG", critical=True)
        add(category="multi_citation", saved=f"Who is credited with {work}?",
            new=f"According to the chapter, who is credited with {work}?", answer=answer,
            citations=_cite(2, excerpt) + _cite(8, f"The summary names {name} for {work}."),
            enough=True, expected="REUSE_EXACT_ANSWER", critical=False)
        add(category="refusal", saved=f"Where was {name} born?",
            new=f"Where did {name} study?",
            answer="The supplied passages do not confirm the answer to this question.",
            citations=[], enough=False, expected="RUN_FULL_RAG", critical=True)
        add(category="refusal_same", saved=f"Where was {name} born?",
            new=f"Where was {name} born?",
            answer="The supplied passages do not confirm the answer to this question.",
            citations=[], enough=False, expected="REUSE_EXACT_ANSWER", critical=False)
        add(category="time_context", saved=f"Who is the lead researcher on {work}?",
            new=f"Who was the lead researcher on {work}?",
            answer=f"{name} is the lead researcher on {work}.",
            citations=_cite(9, f"{name} is the lead researcher on {work}."),
            enough=True, expected="RUN_FULL_RAG", critical=True)
    return rows


def main():
    dev = build("dev", DEV_PEOPLE)
    held = build("heldout", HELD_PEOPLE)
    if len(dev) != 60 or len(held) != 240:
        raise SystemExit(f"Unexpected sizes dev={len(dev)} heldout={len(held)}")
    dev_ids = {row["pair_id"] for row in dev}
    held_ids = {row["pair_id"] for row in held}
    if dev_ids & held_ids:
        raise SystemExit("Split ids overlap")
    dev_text = {(row["saved_question"], row["new_question"]) for row in dev}
    held_text = {(row["saved_question"], row["new_question"]) for row in held}
    if dev_text & held_text:
        raise SystemExit("Split question pairs overlap")
    payload = {
        "result_kind": "LABELED_UNEVALUATED",
        "paid_api_calls": 0,
        "model_scored": False,
        "dev_count": len(dev),
        "heldout_count": len(held),
        "pairs": dev + held,
    }
    path = OUT / "verifier_eval_set.json"
    path.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps({"wrote": str(path), "dev": len(dev), "heldout": len(held), "paid_api_calls": 0}))


if __name__ == "__main__":
    main()
