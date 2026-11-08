from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from mykhaya.legal_evidence import queue_acceptance_evidence
from mykhaya.legal_evidence_pdf import build_acceptance_pdf, sha256_text
from mykhaya.legal_evidence_storage import LegalEvidenceStorage


def test_pdf_contains_exact_content_and_certificate_metadata() -> None:
    content = "# Terms\n\nDo not replace this with today's version."
    pdf = build_acceptance_pdf(
        document_name="Terms & Conditions",
        document_version="1.0",
        content_markdown=content,
        account_name="Synthetic User",
        email="synthetic@example.test",
        action_type="user_acceptance",
        accepted_at=datetime(2026, 11, 8, 12, 0, tzinfo=UTC),
        timezone="Europe/London",
        ip_address="203.0.113.10",
        platform="web",
        acceptance_reference="synthetic-acceptance",
        content_sha256=sha256_text(content),
    )
    assert pdf.startswith(b"%PDF-1.4")
    assert content.encode("utf-8") in pdf
    assert sha256_text(content).encode() in pdf
    assert b"synthetic-acceptance" in pdf


@pytest.mark.asyncio
async def test_queue_helper_snapshots_acceptance_and_deduplicates_outbox_key() -> None:
    class FakeSession:
        def __init__(self) -> None:
            self.added = []

        async def flush(self) -> None:
            return None

        def add(self, value) -> None:
            self.added.append(value)

    acceptance_id = uuid4()
    acceptance = SimpleNamespace(
        id=acceptance_id,
        user_id=uuid4(),
        created_at=datetime(2026, 11, 8, 12, 0, tzinfo=UTC),
        ip_address="203.0.113.20",
        platform=SimpleNamespace(value="web"),
        record_type=SimpleNamespace(value="user_acceptance"),
    )
    document = SimpleNamespace(display_name="Terms & Conditions")
    version = SimpleNamespace(version="2.0", content_markdown="# Current terms")
    user = SimpleNamespace(
        email="synthetic@example.test", display_name="Synthetic User", timezone="Europe/London"
    )
    db = FakeSession()

    evidence = await queue_acceptance_evidence(
        db, acceptance=acceptance, document=document, version=version, user=user
    )

    assert evidence.acceptance_id == acceptance_id
    assert evidence.registered_email == user.email
    assert evidence.content_sha256 == sha256_text(version.content_markdown)
    assert db.added[0] is evidence
    assert db.added[1].topic == "legal.acceptance_evidence"
    assert db.added[1].dedupe_key == f"legal.acceptance_evidence:{acceptance_id}"


@pytest.mark.asyncio
async def test_storage_rejects_path_traversal_and_preserves_existing_pdf(tmp_path) -> None:
    storage = LegalEvidenceStorage(tmp_path / "private")

    with pytest.raises(ValueError):
        await storage.save_once("../outside.pdf", b"attacker")

    await storage.save_once("evidence.pdf", b"original")
    await storage.save_once("evidence.pdf", b"replacement")

    assert await storage.load("evidence.pdf") == b"original"
