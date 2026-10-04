from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Protocol

from mykhaya.config import Settings


class VehiclePhotoStorage(Protocol):
    async def save(self, key: str, data: bytes) -> None: ...
    async def load(self, key: str) -> bytes | None: ...
    async def delete(self, key: str) -> None: ...


class LocalVehiclePhotoStorage:
    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir.resolve()
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, key: str) -> Path:
        if "/" in key or "\\" in key or key in {".", ".."}:
            raise ValueError("Invalid vehicle photo storage key")
        path = (self._base_dir / key).resolve()
        if path.parent != self._base_dir:
            raise ValueError("Invalid vehicle photo storage key")
        return path

    async def save(self, key: str, data: bytes) -> None:
        await asyncio.to_thread(self._path_for(key).write_bytes, data)

    async def load(self, key: str) -> bytes | None:
        try:
            return await asyncio.to_thread(self._path_for(key).read_bytes)
        except FileNotFoundError:
            return None

    async def delete(self, key: str) -> None:
        try:
            await asyncio.to_thread(self._path_for(key).unlink)
        except FileNotFoundError:
            pass


def get_vehicle_photo_storage(settings: Settings) -> LocalVehiclePhotoStorage:
    return LocalVehiclePhotoStorage(Path(settings.vehicle_photo_storage_dir))


def vehicle_photo_filename() -> str:
    return f"{uuid.uuid4()}.webp"
