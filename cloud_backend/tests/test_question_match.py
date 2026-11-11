"""Strict canonical keys. A different character is a different question."""
from bookrag_cloud.question_match import (
    ANSWER_PIPELINE_VERSION,
    LEGACY_PIPELINE_VERSION,
    canonicalize_question,
    is_same_question,
)


def test_exact_repeat_ignores_only_edges_and_one_question_mark():
    assert canonicalize_question("  Who is Neil Armstrong?  ") == "Who is Neil Armstrong"
    assert canonicalize_question("Who   is\tNeil Armstrong ?") == "Who is Neil Armstrong"
    assert is_same_question("Who is Neil Armstrong?", "Who is Neil Armstrong")
    assert is_same_question("Who is Neil Armstrong?", "  Who is Neil Armstrong ?  ")


def test_apostrophe_glyphs_match_and_possessives_stay():
    assert canonicalize_question("Who is Neil Armstrong’s friend?") == "Who is Neil Armstrong's friend"
    assert canonicalize_question("Who is Neil Armstrong`s friend?") == "Who is Neil Armstrong's friend"
    assert "s" in canonicalize_question("Armstrong's")
    assert canonicalize_question("Who's Neil Armstrong?") == "Who's Neil Armstrong"


def test_required_negative_examples_do_not_match():
    pairs = [
        ("What is C++?", "What is C#?"),
        ("Is the value 3.5?", "Is the value 3,5?"),
        ("Was the result A/B?", "Was the result A-B?"),
        ("What did his father do?", "What did her father do?"),
        ("What is my result?", "What is your result?"),
        ("Was it salt and pepper?", "Was it salt or pepper?"),
        ("Who is the president of France?", "Who was the president of France?"),
        ("Who was the first person on the Moon?", "Who was the second person on the Moon?"),
        ("Who was his father?", "Who was his mother?"),
        ("What does US mean here?", "What does us mean here?"),
    ]
    for left, right in pairs:
        assert not is_same_question(left, right), (left, right)
        assert canonicalize_question(left) != canonicalize_question(right)


def test_capitalization_word_order_and_negation_stay_distinct():
    assert not is_same_question("Who is Neil Armstrong?", "who is neil armstrong?")
    assert not is_same_question("Who is Neil Armstrong?", "Who Armstrong Neil is?")
    assert not is_same_question("Who is the president of France?", "Who is not the president of France?")
    assert not is_same_question("Who is Neil Armstrong?", "Who is Neil Armstrong??")


def test_legacy_pipeline_is_a_different_cache_namespace():
    assert ANSWER_PIPELINE_VERSION != LEGACY_PIPELINE_VERSION
    assert ANSWER_PIPELINE_VERSION.endswith("strict-q-v1")
