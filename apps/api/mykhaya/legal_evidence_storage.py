from __future__ import annotations

import asyncio
import uuid
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
        if path.exists():
            return
        await asyncio.to_thread(path.write_bytes, data)

    async def load(self, key: str) -> bytes | None:
        try:
            return await asyncio.to_thread(self._path(key).read_bytes)
        except FileNotFoundError:
            return None


def get_legal_evidence_storage(settings: Settings) -> LegalEvidenceStorage:
    return LegalEvidenceStorage(Path(settings.legal_evidence_storage_dir))


def evidence_filename() -> str:
    return f"{uuid.uuid4()}.pdf"
