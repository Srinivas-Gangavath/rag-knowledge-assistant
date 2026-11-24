from pathlib import Path

import pytest

from app.services.document_errors import InvalidPdfError
from app.services.pdf_parser import PdfParser, clean_extracted_text
from tests.helpers.pdfs import build_pdf


def test_clean_extracted_text_normalizes_whitespace():
    cleaned = clean_extracted_text("Hello   world\r\n\n\n\nNext\t\tline  ")
    assert cleaned == "Hello world\n\nNext line"


def test_parser_extracts_multipage_text_and_page_numbers(tmp_path: Path):
    pdf_path = tmp_path / "original.pdf"
    pdf_path.write_bytes(build_pdf(["First page text", "Second page text", "Third page text"]))

    pages = PdfParser().parse_path(pdf_path)

    assert [page.page_number for page in pages] == [1, 2, 3]
    assert "First page text" in pages[0].text
    assert "Second page text" in pages[1].text
    assert "Third page text" in pages[2].text


def test_parser_skips_empty_page_text_but_keeps_page_numbers(tmp_path: Path):
    pdf_path = tmp_path / "original.pdf"
    pdf_path.write_bytes(build_pdf(["Keep this", "", "Also keep this"]))

    pages = PdfParser().parse_path(pdf_path)

    assert len(pages) == 3
    assert pages[0].page_number == 1
    assert pages[0].text
    assert pages[1].page_number == 2
    assert pages[1].text == ""
    assert pages[2].page_number == 3
    assert pages[2].text


def test_parser_entirely_empty_pdf(tmp_path: Path):
    pdf_path = tmp_path / "original.pdf"
    pdf_path.write_bytes(build_pdf(["", ""]))

    pages = PdfParser().parse_path(pdf_path)

    assert len(pages) == 2
    assert all(page.text == "" for page in pages)


def test_parser_rejects_invalid_pdf(tmp_path: Path):
    pdf_path = tmp_path / "broken.pdf"
    pdf_path.write_bytes(b"this is not a pdf")

    with pytest.raises(InvalidPdfError):
        PdfParser().parse_path(pdf_path)


def test_parser_rejects_malformed_pdf(tmp_path: Path):
    pdf_path = tmp_path / "malformed.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\nthis is not a complete pdf")

    with pytest.raises(InvalidPdfError):
        PdfParser().parse_path(pdf_path)
