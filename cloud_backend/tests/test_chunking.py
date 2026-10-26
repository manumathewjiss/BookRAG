from io import BytesIO

import pytest
from pypdf import PdfReader, PdfWriter

from bookrag_cloud.chunking import PasswordProtectedPdfError, extract_chunks
from tests.pdf_fixture import two_page_pdf


def encrypted_fixture(user_password: str) -> bytes:
    writer = PdfWriter()
    writer.append_pages_from_reader(PdfReader(BytesIO(two_page_pdf(
        "First page says copper.", "Second page says cobalt blue."
    ))))
    writer.encrypt(user_password=user_password, owner_password="fixture-owner-password")
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


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


def test_empty_password_encrypted_pdf_keeps_text_and_source_pages():
    pdf = encrypted_fixture("")
    assert PdfReader(BytesIO(pdf)).is_encrypted
    pages, chunks = extract_chunks(pdf, max_pages=2, max_passages=2)
    assert pages == 2
    assert [(row["pdf_page"], row["text"]) for row in chunks] == [
        (1, "First page says copper."), (2, "Second page says cobalt blue.")
    ]
    with pytest.raises(ValueError, match="page limit"):
        extract_chunks(pdf, max_pages=1, max_passages=2)
    with pytest.raises(ValueError, match="passage limit"):
        extract_chunks(pdf, max_pages=2, max_passages=1)


def test_nonempty_password_pdf_fails_closed():
    pdf = encrypted_fixture("a-private-password")
    with pytest.raises(PasswordProtectedPdfError, match="requires a password"):
        extract_chunks(pdf, max_pages=2, max_passages=2)
