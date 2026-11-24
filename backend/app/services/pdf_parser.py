from dataclasses import dataclass
import re
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.core.logging import get_logger
from app.services.document_errors import InvalidPdfError

logger = get_logger(__name__)


@dataclass(frozen=True)
class PageText:
    page_number: int
    text: str


def clean_extracted_text(text: str) -> str:
    """Conservative normalization. Does not rewrite or summarize the source."""
    cleaned = text.replace("\x00", "")
    cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r" *\n *", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


class PdfParser:
    def parse_path(self, path: str | Path) -> list[PageText]:
        try:
            reader = PdfReader(str(path))
        except (PdfReadError, OSError, ValueError) as exc:
            logger.error("PDF parsing failed (%s)", type(exc).__name__)
            raise InvalidPdfError() from exc

        if getattr(reader, "is_encrypted", False):
            logger.error("PDF parsing failed because the file is encrypted")
            raise InvalidPdfError()

        pages: list[PageText] = []
        for index, page in enumerate(reader.pages, start=1):
            try:
                extracted = page.extract_text() or ""
            except Exception as exc:
                logger.error("PDF page extraction failed (%s)", type(exc).__name__)
                raise InvalidPdfError() from exc
            pages.append(PageText(page_number=index, text=clean_extracted_text(extracted)))
        return pages
