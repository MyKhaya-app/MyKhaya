"""Storage seam for processed Meal Plans images."""

from __future__ import annotations

import uuid
from pathlib import Path

from mykhaya.attachments.storage import LocalAttachmentStorage
from mykhaya.config import Settings


def get_meal_image_storage(settings: Settings) -> LocalAttachmentStorage:
    return LocalAttachmentStorage(Path(settings.meal_image_storage_dir))


def meal_image_filename() -> str:
    return f"{uuid.uuid4()}.webp"
