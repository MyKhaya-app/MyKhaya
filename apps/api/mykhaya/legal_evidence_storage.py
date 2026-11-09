from __future__ import annotations

import asyncio
import os
import re
import tempfile
import uuid
from datetime import date, datetime
from pathlib import Path

from mykhaya.config import Settings


class LegalEvidenceStorage:
    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir.resolve()
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        if "/" in key or "\\" in key or key in {".", ".."}:
            raise ValueError("Invalid legal evidence storage key")
        path = (self._base_dir / key).resolve()
        if path.parent != self._base_dir:
            raise ValueError("Invalid legal evidence storage key")
        return path

    async def save_once(self, key: str, data: bytes) -> None:
        path = self._path(key)

        def write_atomically() -> None:
            if path.exists():
                if path.read_bytes() != data:
                    raise OSError(
                        "Existing legal evidence file differs from the immutable artefact"
                    )
                return
            fd, temporary_name = tempfile.mkstemp(
                dir=self._base_dir, prefix=f".{path.name}.", suffix=".tmp"
            )
            try:
                with os.fdopen(fd, "wb") as temporary:
                    temporary.write(data)
                    temporary.flush()
                    os.fsync(temporary.fileno())
                try:
                    # A hard link gives us an atomic create-without-replace:
                    # another worker can win the race, but an existing final
                    # artefact is never overwritten.
                    os.link(temporary_name, path)
                except FileExistsError:
                    pass
            finally:
                try:
                    os.unlink(temporary_name)
                except FileNotFoundError:
                    pass

        await asyncio.to_thread(write_atomically)

    async def load(self, key: str) -> bytes | None:
        try:
            return await asyncio.to_thread(self._path(key).read_bytes)
        except FileNotFoundError:
            return None


def get_legal_evidence_storage(settings: Settings) -> LegalEvidenceStorage:
    return LegalEvidenceStorage(Path(settings.legal_evidence_storage_dir))


def evidence_filename(evidence_id: uuid.UUID | str | None = None) -> str:
    return f"{evidence_id or uuid.uuid4()}.pdf"


def evidence_download_filename(
    document_name: str, document_version: str, accepted_at: date | datetime
) -> str:
    def slug(value: str) -> str:
        return re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-") or "document"

    accepted_date = accepted_at.date() if isinstance(accepted_at, datetime) else accepted_at
    return (
        f"MyKhaya-{slug(document_name)}-v{slug(document_version)}-{accepted_date.isoformat()}.pdf"
    )
