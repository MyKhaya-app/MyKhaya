"""Avatar file storage abstraction.

Deliberately small: every filesystem touch for avatars goes through this interface so
the local-disk backend can be swapped for S3-compatible object storage later without
changing the image-processing pipeline or the /users/me/avatar routes. No S3 backend
is implemented yet — this is the seam for one, not the thing itself.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Protocol

from mykhaya.config import Settings


class AvatarStorage(Protocol):
    async def save(self, key: str, data: bytes) -> None: ...
    async def load(self, key: str) -> bytes | None: ...
    async def delete(self, key: str) -> None: ...


class LocalAvatarStorage:
    """Stores avatars as files under one persistent directory (a Docker volume in
    every deployment this project currently targets). `key` is always a
    server-generated filename (see _avatar_filename() in mykhaya/routers/users.py) —
    never a client-supplied filename or path.
    """

    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir.resolve()
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, key: str) -> Path:
        # Defence in depth, not the primary control: callers only ever pass the
        # UUID-based filename this module generates, never user input.
        if "/" in key or "\\" in key or key in {".", ".."}:
            raise ValueError("Invalid avatar storage key")
        path = (self._base_dir / key).resolve()
        if path.parent != self._base_dir:
            raise ValueError("Invalid avatar storage key")
        return path

    async def save(self, key: str, data: bytes) -> None:
        await asyncio.to_thread(self._path_for(key).write_bytes, data)

    async def load(self, key: str) -> bytes | None:
        path = self._path_for(key)
        try:
            return await asyncio.to_thread(path.read_bytes)
        except FileNotFoundError:
            return None

    async def delete(self, key: str) -> None:
        path = self._path_for(key)
        try:
            await asyncio.to_thread(path.unlink)
        except FileNotFoundError:
            pass


def get_avatar_storage(settings: Settings) -> LocalAvatarStorage:
    return LocalAvatarStorage(Path(settings.avatar_storage_dir))
