from bookrag_cloud.chunking import extract_chunks
from tests.pdf_fixture import two_page_pdf


def test_uploaded_pdf_keeps_one_based_source_pages():
    pdf = two_page_pdf("First page says copper.", "Second page says cobalt blue.")
    pages, chunks = extract_chunks(pdf, max_pages=10, max_passages=10)
    assert pages == 2
    assert [row["pdf_page"] for row in chunks] == [1, 2]
    assert "copper" in chunks[0]["text"]
    assert "cobalt blue" in chunks[1]["text"]


def test_chunks_do_not_cross_pdf_page_boundary():
    pdf = two_page_pdf("alpha " * 1200, "unique second page")
    pages, chunks = extract_chunks(pdf, max_pages=10, max_passages=30)
    assert pages == 2 and len(chunks) > 2
    assert all("unique" not in row["text"] for row in chunks if row["pdf_page"] == 1)
    assert any("unique" in row["text"] for row in chunks if row["pdf_page"] == 2)
