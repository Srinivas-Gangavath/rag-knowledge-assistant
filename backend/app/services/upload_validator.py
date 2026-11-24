"""Server-side validation for PDF uploads.

The original filename is untrusted metadata. It is never used as a filesystem path.
"""

from io import BytesIO
from pathlib import PurePosixPath, PureWindowsPath

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.core.config import Settings
from app.services.document_errors import (
    EmptyFileError,
    FileTooLargeError,
    InvalidPdfError,
    MissingUploadError,
    UnsupportedFileTypeError,
)

PDF_MAGIC = b"%PDF"
ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "application/x-pdf",
    "application/octet-stream",
}


def original_filename_for_metadata(filename: str | None) -> str:
    """Keep a display name only. Strip path components and control characters."""
    if not filename:
        return "upload.pdf"
    name = PureWindowsPath(filename).name
    name = PurePosixPath(name).name
    name = "".join(char for char in name if char.isprintable()).strip()
    return (name or "upload.pdf")[:255]


def validate_pdf_upload(
    filename: str | None,
    content_type: str | None,
    data: bytes,
    settings: Settings,
) -> None:
    if filename is None and not data:
        raise MissingUploadError()
    if not data:
        raise EmptyFileError()
    if len(data) > settings.max_upload_size_bytes:
        raise FileTooLargeError()

    extension = PurePosixPath(original_filename_for_metadata(filename)).suffix.lower()
    if extension != ".pdf":
        raise UnsupportedFileTypeError()

    normalized_type = (content_type or "").split(";")[0].strip().lower()
    if normalized_type and normalized_type not in ALLOWED_CONTENT_TYPES:
        raise UnsupportedFileTypeError()

    if not data.lstrip().startswith(PDF_MAGIC):
        raise InvalidPdfError()

    try:
        reader = PdfReader(BytesIO(data))
        if getattr(reader, "is_encrypted", False):
            raise InvalidPdfError()
        _ = len(reader.pages)
    except InvalidPdfError:
        raise
    except (PdfReadError, OSError, ValueError) as exc:
        raise InvalidPdfError() from exc
