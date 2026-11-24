"""Standalone live E2E verification. No app imports.

Run from the repository root:

  python backend/scripts/smoke_e2e.py

Or from inside the backend container (API on localhost:8000):

  python -m scripts.smoke_e2e
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from io import BytesIO

import httpx

BASE_URL = os.getenv("BASE_URL", "http://localhost:8000").rstrip("/")
PDF_TEXT = "The ACME refund policy allows returns within 45 days of purchase."
QUESTION = "What is the refund period?"
POLL_INTERVAL_SECONDS = 3
POLL_TIMEOUT_SECONDS = 60
CHAT_TIMEOUT_SECONDS = 90


def _escape_pdf(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _raw_pdf_bytes(text: str) -> bytes:
    stream = f"BT /F1 12 Tf 72 720 Td ({_escape_pdf(text)}) Tj ET"
    objects = {
        1: "<< /Type /Catalog /Pages 2 0 R >>",
        2: "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        3: (
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            "/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>"
        ),
        4: (
            f"<< /Length {len(stream.encode('latin-1', 'replace'))} >>\n"
            f"stream\n{stream}\nendstream"
        ),
        5: "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }
    parts = [b"%PDF-1.4\n"]
    offsets = {0: 0}
    for object_id in range(1, 6):
        offsets[object_id] = sum(len(part) for part in parts)
        parts.append(
            f"{object_id} 0 obj\n{objects[object_id]}\nendobj\n".encode(
                "latin-1",
                "replace",
            )
        )
    xref_start = sum(len(part) for part in parts)
    xref = ["xref\n0 6\n", "0000000000 65535 f \n"]
    for object_id in range(1, 6):
        xref.append(f"{offsets[object_id]:010d} 00000 n \n")
    trailer = (
        f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref_start}\n%%EOF\n"
    )
    parts.append("".join(xref).encode("ascii"))
    parts.append(trailer.encode("ascii"))
    return b"".join(parts)


def create_test_pdf() -> bytes:
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas

        buffer = BytesIO()
        drawing = canvas.Canvas(buffer, pagesize=letter)
        drawing.drawString(72, 720, PDF_TEXT)
        drawing.save()
        return buffer.getvalue()
    except Exception:
        pass

    try:
        from fpdf import FPDF

        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Helvetica", size=12)
        pdf.multi_cell(0, 10, PDF_TEXT)
        return bytes(pdf.output())
    except Exception:
        pass

    return _raw_pdf_bytes(PDF_TEXT)


def main() -> int:
    print(f"Live RAG E2E  BASE_URL={BASE_URL}")
    passed = 0
    total = 6
    started_all = time.perf_counter()
    document_id: str | None = None
    temp_pdf = None

    try:
        temp_pdf = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        temp_pdf.write(create_test_pdf())
        temp_pdf.close()

        with httpx.Client(base_url=BASE_URL, timeout=CHAT_TIMEOUT_SECONDS) as client:
            # 1. Health
            try:
                started = time.perf_counter()
                response = client.get("/api/v1/health")
                elapsed = time.perf_counter() - started
                body = response.json()
                if response.status_code == 200 and body.get("status") == "ok":
                    print(f"[PASS] health  {elapsed:.2f}s  {body}")
                    passed += 1
                else:
                    print(
                        f"[FAIL] health  {elapsed:.2f}s  "
                        f"HTTP {response.status_code} {body}"
                    )
            except Exception as exc:
                print(f"[FAIL] health  {exc}")

            # 2 / 3. Upload
            try:
                started = time.perf_counter()
                with open(temp_pdf.name, "rb") as handle:
                    response = client.post(
                        "/api/v1/documents",
                        files={"file": ("acme-refund.pdf", handle, "application/pdf")},
                    )
                elapsed = time.perf_counter() - started
                if response.status_code != 201:
                    print(
                        f"[FAIL] upload  {elapsed:.2f}s  "
                        f"HTTP {response.status_code} {response.text[:200]}"
                    )
                else:
                    payload = response.json()
                    document_id = payload.get("id")
                    if not document_id:
                        print(f"[FAIL] upload  {elapsed:.2f}s  missing document_id")
                    else:
                        print(f"[PASS] upload  {elapsed:.2f}s  document_id={document_id}")
                        passed += 1
            except Exception as exc:
                print(f"[FAIL] upload  {exc}")

            # 4. Poll for COMPLETED
            try:
                if not document_id:
                    raise RuntimeError("skipped: no document_id")
                started = time.perf_counter()
                status = None
                deadline = time.time() + POLL_TIMEOUT_SECONDS
                while time.time() < deadline:
                    response = client.get(f"/api/v1/documents/{document_id}")
                    if response.status_code != 200:
                        raise RuntimeError(
                            f"HTTP {response.status_code} {response.text[:200]}"
                        )
                    status = response.json().get("status")
                    if status == "COMPLETED":
                        break
                    if status == "FAILED":
                        raise RuntimeError("document status=FAILED")
                    time.sleep(POLL_INTERVAL_SECONDS)
                elapsed = time.perf_counter() - started
                if status == "COMPLETED":
                    print(f"[PASS] ready  {elapsed:.2f}s  COMPLETED")
                    passed += 1
                else:
                    print(
                        f"[FAIL] ready  {elapsed:.2f}s  "
                        f"timeout status={status}"
                    )
            except Exception as exc:
                print(f"[FAIL] ready  {exc}")

            # 5. Chat
            try:
                started = time.perf_counter()
                response = client.post(
                    "/api/v1/chat",
                    json={"question": QUESTION},
                )
                elapsed = time.perf_counter() - started
                if response.status_code != 200:
                    print(
                        f"[FAIL] chat  {elapsed:.2f}s  "
                        f"HTTP {response.status_code} {response.text[:200]}"
                    )
                else:
                    payload = response.json()
                    answer = payload.get("answer")
                    sources = payload.get("sources") or []
                    if not isinstance(answer, str) or not answer.strip():
                        print(f"[FAIL] chat  {elapsed:.2f}s  empty answer")
                    elif len(sources) < 1:
                        print(
                            f"[FAIL] chat  {elapsed:.2f}s  "
                            f"no sources  answer={answer!r}"
                        )
                    else:
                        source = sources[0]
                        filename = source.get("filename")
                        page = source.get("page_number")
                        print(
                            f"[PASS] chat  {elapsed:.2f}s  "
                            f"answer={answer!r}  source={filename}  page={page}"
                        )
                        passed += 1
            except Exception as exc:
                print(f"[FAIL] chat  {exc}")

            # 6. Cleanup API
            try:
                if not document_id:
                    raise RuntimeError("skipped: no document_id")
                started = time.perf_counter()
                response = client.delete(f"/api/v1/documents/{document_id}")
                elapsed = time.perf_counter() - started
                if response.status_code == 204:
                    print(f"[PASS] cleanup  {elapsed:.2f}s  HTTP 204")
                    passed += 1
                else:
                    print(
                        f"[FAIL] cleanup  {elapsed:.2f}s  "
                        f"HTTP {response.status_code} {response.text[:200]}"
                    )
            except Exception as exc:
                print(f"[FAIL] cleanup  {exc}")
    finally:
        if temp_pdf is not None:
            try:
                os.unlink(temp_pdf.name)
            except OSError:
                pass

    total_elapsed = time.perf_counter() - started_all
    print(f"SUMMARY  {passed}/{total} passed  {total_elapsed:.2f}s")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
