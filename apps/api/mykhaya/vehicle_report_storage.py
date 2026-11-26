from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

from mykhaya.config import Settings


class VehicleReportStorage:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir.resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        if "/" in key or "\\" in key or key in {".", ".."}:
            raise ValueError("Invalid vehicle report storage key")
        path = (self.base_dir / key).resolve()
        if path.parent != self.base_dir:
            raise ValueError("Invalid vehicle report storage key")
        return path

    async def save(self, key: str, data: bytes) -> None:
        path = self._path(key)

        def write() -> None:
            fd, temp = tempfile.mkstemp(dir=self.base_dir, prefix=".report-", suffix=".tmp")
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temp, path)
            finally:
                if os.path.exists(temp):
                    os.unlink(temp)

        await asyncio.to_thread(write)

    async def load(self, key: str) -> bytes | None:
        try:
            return await asyncio.to_thread(self._path(key).read_bytes)
        except FileNotFoundError:
            return None

    async def delete(self, key: str) -> None:
        try:
            await asyncio.to_thread(self._path(key).unlink)
        except FileNotFoundError:
            pass


def get_vehicle_report_storage(settings: Settings) -> VehicleReportStorage:
    return VehicleReportStorage(Path(settings.legal_evidence_storage_dir) / "vehicle-reports")
