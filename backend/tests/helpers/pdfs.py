"""Minimal PDF-1.4 fixtures for parser and upload tests."""


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def build_pdf(pages: list[str]) -> bytes:
    """Build a small valid PDF. Empty strings create pages with no extractable text."""
    if not pages:
        pages = [""]

    page_count = len(pages)
    font_id = 3 + (2 * page_count)
    objects: dict[int, str] = {}
    kids: list[str] = []

    for index, text in enumerate(pages):
        page_id = 3 + (2 * index)
        content_id = 4 + (2 * index)
        kids.append(f"{page_id} 0 R")
        stream = f"BT /F1 12 Tf 72 720 Td ({_escape(text)}) Tj ET"
        stream_bytes = stream.encode("latin-1", "replace")
        objects[content_id] = (
            f"<< /Length {len(stream_bytes)} >>\nstream\n{stream}\nendstream"
        )
        objects[page_id] = (
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Contents {content_id} 0 R "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> >>"
        )

    objects[1] = "<< /Type /Catalog /Pages 2 0 R >>"
    objects[2] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {page_count} >>"
    objects[font_id] = "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"

    parts = [b"%PDF-1.4\n"]
    offsets = {0: 0}
    for object_id in range(1, font_id + 1):
        offsets[object_id] = sum(len(part) for part in parts)
        parts.append(
            f"{object_id} 0 obj\n{objects[object_id]}\nendobj\n".encode("latin-1", "replace")
        )

    xref_start = sum(len(part) for part in parts)
    xref_lines = [f"xref\n0 {font_id + 1}\n", "0000000000 65535 f \n"]
    for object_id in range(1, font_id + 1):
        xref_lines.append(f"{offsets[object_id]:010d} 00000 n \n")
    trailer = (
        f"trailer\n<< /Size {font_id + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_start}\n%%EOF\n"
    )
    parts.append("".join(xref_lines).encode("ascii"))
    parts.append(trailer.encode("ascii"))
    return b"".join(parts)


POLICY_PAGES = [
    "Company Policy. Refunds: Customers may request a refund within 30 days of purchase.",
    "Support: Customer support is available Monday through Friday.",
    "Office: The company office is located in Bengaluru.",
    "Security: Passwords must be changed every 90 days.",
]
