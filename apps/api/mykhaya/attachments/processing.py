"""Support-ticket attachment image processing: decode, validate, strip
metadata, normalise orientation, cap dimensions, and re-encode. The server
never trusts the client-supplied MIME type or filename — the only thing that
decides whether an upload is accepted is whether it can actually be decoded
as one of the supported image formats below.

Deliberately a separate module from mykhaya.avatars.processing, not a reuse
of it — a support attachment (a bug-report screenshot) must keep its own
aspect ratio and framing, unlike an avatar, which is always cropped to a
square. The safety posture (decode-result-based format acceptance, full
metadata strip, resource limits) mirrors avatars.processing intentionally,
since that's this codebase's proven approach to untrusted image uploads.
"""

from __future__ import annotations

import io

import structlog
from PIL import Image, ImageOps

try:
    import pillow_heif

    pillow_heif.register_heif_opener()
    HEIC_SUPPORTED = True
except ImportError:  # pragma: no cover - depends on platform wheel availability
    HEIC_SUPPORTED = False

# A bug-report screenshot is a full-resolution device screen capture, not a
# small profile photo — cap the longest edge rather than force a fixed
# square crop (unlike avatars.processing.AVATAR_SIZE).
MAX_ATTACHMENT_DIMENSION = 2400
MAX_ATTACHMENT_PIXELS = 40_000_000
OUTPUT_FORMAT = "WEBP"
OUTPUT_CONTENT_TYPE = "image/webp"
log = structlog.get_logger("attachment_processing")

# Pillow's format sniffing recognises far more than we want to accept (GIF,
# BMP, TIFF, ICO...). Restrict to the raster photo formats support
# attachments actually advertise support for (Phase 2A: "images only ...
# JPEG/PNG/HEIC"), regardless of what Pillow itself is capable of opening.
ALLOWED_PILLOW_FORMATS = {"JPEG", "PNG", "WEBP", "HEIF"}


class UnsupportedImageError(Exception):
    """The upload could not be safely processed as a supported attachment
    image. The message is written to be shown to the end user as-is."""


class AttachmentResourceError(Exception):
    """The upload exceeds safe decoded-image resource limits."""


def process_attachment_upload(raw: bytes) -> bytes:
    """Decode `raw`, strip all metadata (including EXIF/GPS), normalise
    orientation, cap dimensions (preserving aspect ratio) to
    MAX_ATTACHMENT_DIMENSION, and re-encode as WebP. Raises
    UnsupportedImageError if the data can't be safely processed as an image,
    or AttachmentResourceError if it exceeds safe decode limits."""
    try:
        image = Image.open(io.BytesIO(raw))
        image_format = (image.format or "").upper()
        pixel_count = image.width * image.height
        log.info(
            "attachment_image_opened",
            bytes=len(raw),
            image_format=image_format or "(unknown)",
            width=image.width,
            height=image.height,
            pixel_count=pixel_count,
            heic_supported=HEIC_SUPPORTED,
        )
        if pixel_count > MAX_ATTACHMENT_PIXELS:
            raise AttachmentResourceError
        image.load()  # force full decode now rather than lazily on first use below
    except AttachmentResourceError:
        log.warning(
            "attachment_image_resource_limit", bytes=len(raw), max_pixels=MAX_ATTACHMENT_PIXELS
        )
        raise
    except Image.DecompressionBombError as cause:
        log.warning(
            "attachment_image_decompression_bomb",
            bytes=len(raw),
            exception_type=type(cause).__name__,
        )
        raise AttachmentResourceError from cause
    except UnsupportedImageError:
        raise
    except Exception as cause:
        log.warning(
            "attachment_image_decode_failed",
            bytes=len(raw),
            exception_type=type(cause).__name__,
            exception_message=str(cause),
        )
        raise UnsupportedImageError(
            "That file could not be read as an image. "
            "Please upload a JPEG, PNG, HEIC or WebP photo."
        ) from cause

    image_format = (image.format or "").upper()
    if image_format == "HEIF" and not HEIC_SUPPORTED:
        raise UnsupportedImageError(
            "HEIC/HEIF photos are not supported on this server. Please use JPEG, PNG or WebP."
        )
    if image_format not in ALLOWED_PILLOW_FORMATS:
        raise UnsupportedImageError(
            "That image format is not supported. Please upload a JPEG, PNG, HEIC or WebP photo."
        )

    # Auto-orient from EXIF before discarding it, then rebuild a brand new
    # image from just the raw pixel bytes — frombytes() carries no .info
    # dict, so this is a clean break from any EXIF/GPS/ICC/textual metadata
    # on the original upload.
    oriented = ImageOps.exif_transpose(image) or image
    oriented = oriented.convert("RGB")
    clean = Image.frombytes("RGB", oriented.size, oriented.tobytes())

    if max(clean.size) > MAX_ATTACHMENT_DIMENSION:
        clean.thumbnail(
            (MAX_ATTACHMENT_DIMENSION, MAX_ATTACHMENT_DIMENSION), resample=Image.Resampling.LANCZOS
        )

    buffer = io.BytesIO()
    clean.save(buffer, format=OUTPUT_FORMAT, quality=85, method=6)
    return buffer.getvalue()
