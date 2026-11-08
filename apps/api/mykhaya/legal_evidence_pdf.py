from __future__ import annotations

import hashlib
import textwrap
from datetime import datetime


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _pdf_escape(value: str) -> bytes:
    return (
        value.encode("latin-1", "replace")
        .replace(b"\\", b"\\\\")
        .replace(b"(", b"\\(")
        .replace(b")", b"\\)")
    )


def build_acceptance_pdf(
    *,
    document_name: str,
    document_version: str,
    content_markdown: str,
    account_name: str | None,
    email: str | None,
    action_type: str,
    accepted_at: datetime,
    timezone: str,
    ip_address: str | None,
    platform: str,
    acceptance_reference: str,
    content_sha256: str,
) -> bytes:
    lines = [
        "MYKHAYA | LEGAL ACCEPTANCE CERTIFICATE",
        "",
        f"Document name: {document_name}",
        f"Document version: {document_version}",
        f"Account holder: {account_name or 'Not recorded'}",
        f"Registered email: {email or 'Not recorded'}",
        f"Acceptance action: {action_type}",
        f"Exact date and time: {accepted_at.isoformat()}",
        f"Timezone: {timezone}",
        "Recorded public IP: "
        f"{ip_address or 'Unavailable - trusted proxy resolution did not provide one'}",
        f"Platform: {platform}",
        f"Unique acceptance reference: {acceptance_reference}",
        f"Document/evidence SHA-256: {content_sha256}",
        "",
        (
            "This PDF records the exact legal document version and associated acceptance details "
            "retained by MyKhaya."
        ),
        "",
        f"{document_name} — version {document_version}",
        "",
    ]
    for raw in content_markdown.splitlines():
        lines.extend(textwrap.wrap(raw, width=100) or [""])

    pages: list[list[str]] = [lines[i : i + 54] for i in range(0, len(lines), 54)] or [[""]]
    objects: list[bytes] = []
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    page_refs = " ".join(f"{3 + i * 2} 0 R" for i in range(len(pages)))
    objects.append(f"<< /Type /Pages /Kids [{page_refs}] /Count {len(pages)} >>".encode())
    for index, page_lines in enumerate(pages):
        page_obj = 3 + index * 2
        content_obj = page_obj + 1
        stream = b"BT /F1 10 Tf 50 780 Td 14 TL\n" + b"\n".join(
            b"(" + _pdf_escape(line) + b") Tj T*" for line in page_lines
        ) + b"\nET"
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            f"/Resources << /Font << /F1 {3 + len(pages) * 2} 0 R >> >> "
            f"/Contents {content_obj} 0 R >>".encode()
        )
        objects.append(f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    # Keep the exact UTF-8 source snapshot embedded as a PDF comment as well
    # as rendered text. This avoids lossy font encoding changing the legal
    # source that the artefact evidences.
    result = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n%MYKHAYA-LEGAL-CONTENT\n")
    result.extend(content_markdown.encode("utf-8") + b"\n")
    offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(result))
        result.extend(f"{number} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(result)
    result.extend(f"xref\n0 {len(objects)+1}\n0000000000 65535 f \n".encode())
    result.extend(b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets[1:]))
    result.extend(
        f"trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(result)
