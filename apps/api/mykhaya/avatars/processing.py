"""Avatar image processing: decode, validate, strip metadata, normalise orientation,
crop to a square, resize, and re-encode. The server never trusts the client-supplied
MIME type or filename — the only thing that decides whether an upload is accepted is
whether it can actually be decoded as one of the supported image formats below.
"""

from __future__ import annotations

import io

import structlog
from PIL import Image, ImageOps

try:
    import pillow_heif

    pillow_heif.register_heif_opener()  # type: ignore[attr-defined]
    HEIC_SUPPORTED = True
except ImportError:  # pragma: no cover - depends on platform wheel availability
    HEIC_SUPPORTED = False

AVATAR_SIZE = 512
MAX_AVATAR_PIXELS = 40_000_000
OUTPUT_FORMAT = "WEBP"
OUTPUT_CONTENT_TYPE = "image/webp"
log = structlog.get_logger("avatar_processing")

# Pillow's format sniffing recognises far more than we want to accept (GIF, BMP,
# TIFF, ICO...). Restrict to the raster photo formats we actually advertise support
# for, regardless of what Pillow itself is capable of opening.
ALLOWED_PILLOW_FORMATS = {"JPEG", "PNG", "WEBP", "HEIF"}


class UnsupportedImageError(Exception):
    """The upload could not be safely processed as a supported avatar image. The
    message is written to be shown to the end user as-is."""


class AvatarResourceError(Exception):
    """The upload exceeds safe decoded-image resource limits."""


def process_avatar_upload(raw: bytes) -> bytes:
    """Decode `raw`, strip all metadata (including EXIF/GPS), normalise orientation,
    crop to a square, resize to AVATAR_SIZE, and re-encode as WebP. Raises
    UnsupportedImageError if the data can't be safely processed as an image."""
    try:
        image = Image.open(io.BytesIO(raw))
        image_format = (image.format or "").upper()
        pixel_count = image.width * image.height
        log.info(
            "avatar_image_opened",
            bytes=len(raw),
            image_format=image_format or "(unknown)",
            width=image.width,
            height=image.height,
            pixel_count=pixel_count,
            heic_supported=HEIC_SUPPORTED,
        )
        if pixel_count > MAX_AVATAR_PIXELS:
            raise AvatarResourceError
        image.load()  # force full decode now rather than lazily on first use below
    except AvatarResourceError:
        log.warning("avatar_image_resource_limit", bytes=len(raw), max_pixels=MAX_AVATAR_PIXELS)
        raise
    except Image.DecompressionBombError as cause:
        log.warning(
            "avatar_image_decompression_bomb",
            bytes=len(raw),
            exception_type=type(cause).__name__,
        )
        raise AvatarResourceError from cause
    except UnsupportedImageError:
        raise
    except Exception as cause:
        log.warning(
            "avatar_image_decode_failed",
            bytes=len(raw),
            exception_type=type(cause).__name__,
            exception_message=str(cause),
        )
        raise UnsupportedImageError(
            "That file could not be read as an image. Please upload a JPEG, PNG or WebP photo."
        ) from cause

    image_format = (image.format or "").upper()
    if image_format == "HEIF" and not HEIC_SUPPORTED:
        raise UnsupportedImageError(
            "HEIC/HEIF photos are not supported on this server. Please use JPEG, PNG or WebP."
        )
    if image_format not in ALLOWED_PILLOW_FORMATS:
        raise UnsupportedImageError(
            "That image format is not supported. Please upload a JPEG, PNG or WebP photo."
        )

    # Auto-orient from EXIF before discarding it, then rebuild a brand new image from
    # just the raw pixel bytes — frombytes() carries no .info dict, so this is a clean
    # break from any EXIF/GPS/ICC/textual metadata on the original upload.
    oriented = ImageOps.exif_transpose(image) or image
    oriented = oriented.convert("RGB")
    clean = Image.frombytes("RGB", oriented.size, oriented.tobytes())

    square = ImageOps.fit(clean, (AVATAR_SIZE, AVATAR_SIZE), method=Image.Resampling.LANCZOS)

    buffer = io.BytesIO()
    square.save(buffer, format=OUTPUT_FORMAT, quality=85, method=6)
    return buffer.getvalue()
