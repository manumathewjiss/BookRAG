from bookrag_cloud.retrieval import bm25_top, fuse, tokens


def p(index, text):
    return {"id": str(index), "chunk_index": index, "text": text}


def test_bm25_uses_frozen_unicode_word_protocol():
    assert tokens("Gītā, GĪTĀ! 5%") == ["gītā", "gītā", "5"]
    rows = [p(0, "python functions"), p(1, "python python loops"), p(2, "other text")]
    assert [x["id"] for x in bm25_top(rows, "python")] == ["1", "0"]


def test_rrf_preserves_both_lists_and_skips_duplicates():
    a, b, c = p(0, "a"), p(1, "b"), p(2, "c")
    assert [x["id"] for x in fuse([a, b], [b, c])] == ["1", "0", "2"]


def test_empty_keyword_result_keeps_dense():
    assert [x["id"] for x in fuse([p(0, "a")], [])] == ["0"]
