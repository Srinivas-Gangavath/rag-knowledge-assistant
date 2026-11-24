from app.services.document_errors import (
    EmptyFileError,
    FileTooLargeError,
    InvalidPdfError,
    MissingUploadError,
    UnsupportedFileTypeError,
)
from app.services.upload_validator import original_filename_for_metadata, validate_pdf_upload
from tests.conftest import make_settings
from tests.helpers.pdfs import build_pdf
import pytest


def test_original_filename_strips_paths():
    assert original_filename_for_metadata("..\\..\\etc\\passwd.pdf") == "passwd.pdf"
    assert original_filename_for_metadata("../../secret.pdf") == "secret.pdf"
    assert original_filename_for_metadata("C:\\Windows\\System32\\policy.pdf") == "policy.pdf"
    assert original_filename_for_metadata("/etc/passwd.pdf") == "passwd.pdf"


def test_validate_rejects_non_pdf_extension():
    with pytest.raises(UnsupportedFileTypeError):
        validate_pdf_upload("notes.txt", "application/pdf", build_pdf(["hello"]), make_settings())


def test_validate_rejects_wrong_mime_type():
    with pytest.raises(UnsupportedFileTypeError):
        validate_pdf_upload("notes.pdf", "image/png", build_pdf(["hello"]), make_settings())


def test_validate_rejects_oversized_file():
    settings = make_settings(max_upload_size_mb=1)
    data = b"%PDF-1.4\n" + (b"a" * settings.max_upload_size_bytes)
    with pytest.raises(FileTooLargeError):
        validate_pdf_upload("notes.pdf", "application/pdf", data, settings)


def test_validate_rejects_invalid_pdf_bytes():
    with pytest.raises(InvalidPdfError):
        validate_pdf_upload("notes.pdf", "application/pdf", b"hello", make_settings())


def test_validate_rejects_empty_file():
    with pytest.raises(EmptyFileError):
        validate_pdf_upload("notes.pdf", "application/pdf", b"", make_settings())


def test_validate_rejects_missing_upload():
    with pytest.raises(MissingUploadError):
        validate_pdf_upload(None, None, b"", make_settings())


def test_validate_accepts_octet_stream_pdf():
    validate_pdf_upload(
        "notes.pdf",
        "application/octet-stream",
        build_pdf(["hello"]),
        make_settings(),
    )


def test_validate_rejects_renamed_non_pdf():
    with pytest.raises(InvalidPdfError):
        validate_pdf_upload(
            "notes.pdf",
            "application/pdf",
            b"PK\x03\x04this is not a pdf",
            make_settings(),
        )


def test_validate_rejects_renamed_executable():
    with pytest.raises(InvalidPdfError):
        validate_pdf_upload(
            "malicious.pdf",
            "application/pdf",
            b"MZ" + b"\x00" * 64,
            make_settings(),
        )


def test_validate_rejects_encrypted_pdf():
    from io import BytesIO

    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.encrypt("password")
    buffer = BytesIO()
    writer.write(buffer)

    with pytest.raises(InvalidPdfError):
        validate_pdf_upload(
            "secret.pdf",
            "application/pdf",
            buffer.getvalue(),
            make_settings(),
        )
