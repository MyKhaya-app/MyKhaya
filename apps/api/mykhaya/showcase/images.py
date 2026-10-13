"""Showcase imagery: original illustrations, or approved photography.

Every showcase image is stored through the same processing and storage path
as a user upload (avatars.processing / attachments.processing, then the
avatar, meal-image and vehicle-photo storage seams), so it renders exactly
as a real upload does on web and native — never an external URL that could
disappear.

Source of each image, in order:

1. Approved photography dropped into ``mykhaya/showcase/assets/<kind>/`` as
   ``<slug>.jpg|.jpeg|.png|.webp`` (kind = meals, vehicles or avatars). Only
   add files the business holds a licence or release for — see
   docs/operations/apple-testflight-review-fixture.md.
2. Otherwise, an original illustration rendered here with Pillow. These are
   MyKhaya's own work (no third-party artwork), deterministic for a given
   slug, and carry no personal data or metadata.
"""

from __future__ import annotations

import io
import math
import random
from collections.abc import Callable
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from mykhaya.showcase.parker import AvatarArt, MealArt

ASSET_ROOT = Path(__file__).parent / "assets"
_PHOTO_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp")
# Supersampling factor: draw large, downscale with LANCZOS for clean edges.
_SS = 2

RGB = tuple[int, int, int]


def approved_photo(kind: str, slug: str) -> bytes | None:
    """Raw bytes of an approved photograph for this slug, if one is present."""
    for suffix in _PHOTO_SUFFIXES:
        path = ASSET_ROOT / kind / f"{slug}{suffix}"
        if path.is_file():
            return path.read_bytes()
    return None


def _rgb(value: str) -> RGB:
    value = value.lstrip("#")
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))


def _mix(a: RGB, b: RGB, t: float) -> RGB:
    return (
        round(a[0] + (b[0] - a[0]) * t),
        round(a[1] + (b[1] - a[1]) * t),
        round(a[2] + (b[2] - a[2]) * t),
    )


def _shade(colour: RGB, amount: float) -> RGB:
    """amount < 0 darkens towards black, > 0 lightens towards white."""
    return _mix(colour, (0, 0, 0), -amount) if amount < 0 else _mix(colour, (255, 255, 255), amount)


def _png(image: Image.Image, size: tuple[int, int]) -> bytes:
    final = image.resize(size, Image.Resampling.LANCZOS).convert("RGB")
    buffer = io.BytesIO()
    final.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def _vertical_gradient(size: tuple[int, int], top: RGB, bottom: RGB) -> Image.Image:
    width, height = size
    gradient = Image.new("RGB", (1, height))
    for y in range(height):
        gradient.putpixel((0, y), _mix(top, bottom, y / max(height - 1, 1)))
    return gradient.resize(size)


def _soft_shadow(
    canvas: Image.Image, box: tuple[float, float, float, float], opacity: int, blur: float
) -> None:
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).ellipse(box, fill=(40, 30, 20, opacity))
    canvas.alpha_composite(layer.filter(ImageFilter.GaussianBlur(blur)))


# --- Meals --------------------------------------------------------------------------

MEAL_SIZE = (1200, 900)


def _leaf(
    draw: ImageDraw.ImageDraw, x: float, y: float, size: float, angle: float, fill: RGB
) -> None:
    points = []
    for step in range(24):
        t = step / 24 * 2 * math.pi
        px = math.cos(t) * size
        py = math.sin(t) * size * 0.45
        points.append(
            (
                x + px * math.cos(angle) - py * math.sin(angle),
                y + px * math.sin(angle) + py * math.cos(angle),
            )
        )
    draw.polygon(points, fill=fill)
    draw.line(
        [
            (x - math.cos(angle) * size * 0.8, y - math.sin(angle) * size * 0.8),
            (x + math.cos(angle) * size * 0.8, y + math.sin(angle) * size * 0.8),
        ],
        fill=_shade(fill, -0.25),
        width=max(2, int(size * 0.08)),
    )


def _blob(
    draw: ImageDraw.ImageDraw,
    rng: random.Random,
    cx: float,
    cy: float,
    radius: float,
    fill: RGB,
    lumps: int = 9,
) -> None:
    for _ in range(lumps):
        angle = rng.uniform(0, 2 * math.pi)
        dist = rng.uniform(0, radius * 0.45)
        r = radius * rng.uniform(0.45, 0.7)
        x, y = cx + math.cos(angle) * dist, cy + math.sin(angle) * dist
        draw.ellipse((x - r, y - r, x + r, y + r), fill=fill)


def _scatter(
    draw: ImageDraw.ImageDraw,
    rng: random.Random,
    cx: float,
    cy: float,
    radius: float,
    count: int,
    size: tuple[float, float],
    fills: tuple[RGB, ...],
) -> None:
    for _ in range(count):
        angle = rng.uniform(0, 2 * math.pi)
        dist = radius * math.sqrt(rng.uniform(0, 1))
        r = rng.uniform(*size)
        x, y = cx + math.cos(angle) * dist, cy + math.sin(angle) * dist
        draw.ellipse((x - r, y - r, x + r, y + r), fill=rng.choice(fills))


def _plate(canvas: Image.Image, cx: float, cy: float, r: float, rim: RGB = (236, 232, 224)) -> None:
    _soft_shadow(canvas, (cx - r * 0.98, cy - r * 0.86, cx + r * 1.06, cy + r * 1.08), 70, r * 0.08)
    draw = ImageDraw.Draw(canvas)
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(251, 250, 247))
    draw.ellipse(
        (cx - r * 0.97, cy - r * 0.97, cx + r * 0.97, cy + r * 0.97),
        outline=rim,
        width=int(r * 0.02),
    )
    draw.ellipse((cx - r * 0.74, cy - r * 0.74, cx + r * 0.74, cy + r * 0.74), fill=(246, 244, 239))


def _bowl(canvas: Image.Image, cx: float, cy: float, r: float, glaze: RGB, fill: RGB) -> None:
    _soft_shadow(canvas, (cx - r * 0.98, cy - r * 0.86, cx + r * 1.06, cy + r * 1.08), 80, r * 0.08)
    draw = ImageDraw.Draw(canvas)
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=glaze)
    draw.ellipse((cx - r * 0.9, cy - r * 0.9, cx + r * 0.9, cy + r * 0.9), fill=_shade(glaze, 0.35))
    draw.ellipse((cx - r * 0.82, cy - r * 0.82, cx + r * 0.82, cy + r * 0.82), fill=fill)


def _food(canvas: Image.Image, art: MealArt, rng: random.Random) -> None:
    w, h = canvas.size
    cx, cy, r = w * 0.5, h * 0.53, h * 0.38
    primary, secondary, accent = _rgb(art.primary), _rgb(art.secondary), _rgb(art.accent)
    motif = art.motif
    if motif in {"bowl", "soup", "salad"}:
        glaze = (246, 243, 236) if motif != "soup" else (58, 92, 120)
        base = primary if motif != "salad" else _shade(primary, -0.1)
        _bowl(canvas, cx, cy, r, glaze, base)
        draw = ImageDraw.Draw(canvas)
        inner = r * 0.8
        if motif == "bowl":
            # Rice on one side, curry/stir-fry on the other, herbs on top.
            draw.pieslice(
                (cx - inner, cy - inner, cx + inner, cy + inner), 200, 340, fill=secondary
            )
            _scatter(
                draw,
                rng,
                cx,
                cy + inner * 0.15,
                inner * 0.6,
                26,
                (r * 0.05, r * 0.09),
                (_shade(primary, -0.15), _shade(primary, 0.2), (238, 225, 200)),
            )
            for _ in range(9):
                _leaf(
                    draw,
                    cx + rng.uniform(-inner, inner) * 0.6,
                    cy + rng.uniform(-inner, inner) * 0.6,
                    r * 0.07,
                    rng.uniform(0, math.pi),
                    accent,
                )
        elif motif == "soup":
            for i in range(3):
                rr = inner * (0.55 - i * 0.15)
                draw.arc(
                    (cx - rr, cy - rr, cx + rr, cy + rr),
                    20 + i * 60,
                    250 + i * 60,
                    fill=secondary,
                    width=int(r * 0.035),
                )
            for _ in range(5):
                _leaf(
                    draw,
                    cx + rng.uniform(-0.4, 0.4) * inner,
                    cy + rng.uniform(-0.4, 0.4) * inner,
                    r * 0.08,
                    rng.uniform(0, math.pi),
                    accent,
                )
            # Crusty bread beside the bowl.
            bx, by = cx + r * 1.05, cy + r * 0.55
            draw.rounded_rectangle(
                (bx - r * 0.28, by - r * 0.18, bx + r * 0.28, by + r * 0.18),
                radius=r * 0.14,
                fill=(201, 146, 82),
            )
            draw.rounded_rectangle(
                (bx - r * 0.22, by - r * 0.12, bx + r * 0.22, by + r * 0.12),
                radius=r * 0.1,
                fill=(240, 214, 165),
            )
        else:
            for _ in range(36):
                _leaf(
                    draw,
                    cx + rng.uniform(-0.7, 0.7) * inner,
                    cy + rng.uniform(-0.7, 0.7) * inner,
                    r * rng.uniform(0.1, 0.16),
                    rng.uniform(0, math.pi),
                    rng.choice((primary, _shade(primary, 0.25), _shade(primary, -0.2))),
                )
            _scatter(draw, rng, cx, cy, inner * 0.6, 9, (r * 0.07, r * 0.1), (secondary,))
            for _ in range(6):
                x, y = cx + rng.uniform(-0.5, 0.5) * inner, cy + rng.uniform(-0.5, 0.5) * inner
                s = r * 0.08
                draw.rectangle((x - s, y - s, x + s, y + s), fill=accent)
        return
    if motif in {"tray", "brownies"}:
        tw, th = r * 1.5, r * 1.05
        _soft_shadow(canvas, (cx - tw, cy - th * 0.9, cx + tw * 1.04, cy + th * 1.12), 80, r * 0.08)
        draw = ImageDraw.Draw(canvas)
        dish = (238, 236, 230) if motif == "tray" else (214, 206, 196)
        draw.rounded_rectangle((cx - tw, cy - th, cx + tw, cy + th), radius=r * 0.12, fill=dish)
        draw.rounded_rectangle(
            (cx - tw * 0.9, cy - th * 0.86, cx + tw * 0.9, cy + th * 0.86),
            radius=r * 0.08,
            fill=primary,
        )
        if motif == "tray":
            for _ in range(16):
                _blob(
                    draw,
                    rng,
                    cx + rng.uniform(-0.75, 0.75) * tw,
                    cy + rng.uniform(-0.7, 0.7) * th,
                    r * 0.14,
                    secondary,
                    4,
                )
            _scatter(
                draw,
                rng,
                cx,
                cy,
                r * 0.8,
                40,
                (r * 0.015, r * 0.035),
                (accent, _shade(secondary, -0.25)),
            )
        else:
            cols, rows = 4, 3
            cw, ch = tw * 1.8 / cols, th * 1.72 / rows
            for i in range(cols):
                for j in range(rows):
                    x0, y0 = cx - tw * 0.9 + i * cw, cy - th * 0.86 + j * ch
                    draw.rectangle(
                        (x0 + 3, y0 + 3, x0 + cw - 3, y0 + ch - 3),
                        fill=primary,
                        outline=secondary,
                        width=int(r * 0.02),
                    )
                    _scatter(
                        draw,
                        rng,
                        x0 + cw / 2,
                        y0 + ch / 2,
                        cw * 0.3,
                        5,
                        (r * 0.01, r * 0.02),
                        (accent,),
                    )
        return
    if motif in {"burger", "stack"}:
        _plate(canvas, cx, cy + r * 0.1, r)
        draw = ImageDraw.Draw(canvas)
        base_y, width = cy + r * 0.45, r * 0.85
        if motif == "burger":
            layers = (
                (primary, r * 0.18),
                (secondary, r * 0.17),
                ((242, 196, 64), r * 0.05),
                (accent, r * 0.07),
                ((205, 58, 44), r * 0.07),
            )
            y = base_y
            for colour, height in layers:
                draw.rounded_rectangle(
                    (cx - width, y - height, cx + width, y), radius=height / 2, fill=colour
                )
                y -= height * 0.92
            draw.pieslice(
                (cx - width * 1.02, y - r * 0.55, cx + width * 1.02, y + r * 0.42),
                180,
                360,
                fill=primary,
            )
            draw.pieslice(
                (cx - width * 0.9, y - r * 0.47, cx + width * 0.9, y + r * 0.34),
                200,
                300,
                fill=_shade(primary, 0.18),
            )
            for _ in range(14):
                sx = cx + rng.uniform(-0.7, 0.7) * width
                sy = y - rng.uniform(0.08, 0.38) * r
                draw.ellipse(
                    (sx - 5 * _SS, sy - 3 * _SS, sx + 5 * _SS, sy + 3 * _SS), fill=(248, 238, 210)
                )
        else:
            y = base_y
            for index in range(5):
                height = r * 0.13
                tone = _shade(primary, -0.05 * (index % 2))
                draw.rounded_rectangle(
                    (cx - width, y - height, cx + width, y), radius=height / 2, fill=tone
                )
                draw.line(
                    (cx - width * 0.9, y - height * 0.5, cx + width * 0.9, y - height * 0.5),
                    fill=_shade(primary, 0.2),
                    width=int(r * 0.012),
                )
                y -= height * 0.85
            draw.pieslice(
                (cx - width * 0.6, y - r * 0.18, cx + width * 0.4, y + r * 0.28),
                180,
                360,
                fill=(140, 80, 30),
            )
            _scatter(
                draw,
                rng,
                cx,
                y - r * 0.05,
                width * 0.55,
                12,
                (r * 0.05, r * 0.075),
                (secondary, accent, _shade(secondary, 0.15)),
            )
        return
    if motif == "pizza":
        _soft_shadow(
            canvas, (cx - r * 0.98, cy - r * 0.86, cx + r * 1.06, cy + r * 1.08), 70, r * 0.08
        )
        draw = ImageDraw.Draw(canvas)
        draw.ellipse(
            (cx - r * 1.04, cy - r * 1.04, cx + r * 1.04, cy + r * 1.04), fill=(176, 128, 82)
        )
        draw.ellipse((cx - r * 0.98, cy - r * 0.98, cx + r * 0.98, cy + r * 0.98), fill=primary)
        draw.ellipse((cx - r * 0.84, cy - r * 0.84, cx + r * 0.84, cy + r * 0.84), fill=secondary)
        for _ in range(9):
            _blob(
                draw,
                rng,
                cx + rng.uniform(-0.55, 0.55) * r,
                cy + rng.uniform(-0.55, 0.55) * r,
                r * 0.13,
                (250, 244, 228),
                5,
            )
        for _ in range(8):
            _leaf(
                draw,
                cx + rng.uniform(-0.6, 0.6) * r,
                cy + rng.uniform(-0.6, 0.6) * r,
                r * 0.09,
                rng.uniform(0, math.pi),
                accent,
            )
        for k in range(4):
            angle = k * math.pi / 4
            draw.line(
                (
                    cx - math.cos(angle) * r * 0.98,
                    cy - math.sin(angle) * r * 0.98,
                    cx + math.cos(angle) * r * 0.98,
                    cy + math.sin(angle) * r * 0.98,
                ),
                fill=_shade(primary, -0.2),
                width=int(r * 0.012),
            )
        return
    # Plated mains: pasta, roast, plate, wrap, tacos, salmon, omelette.
    _plate(canvas, cx, cy, r)
    draw = ImageDraw.Draw(canvas)
    inner = r * (0.72 if motif == "pasta" else 0.98)
    if motif == "pasta":
        for _ in range(70):
            ox, oy = rng.uniform(-0.55, 0.55) * inner, rng.uniform(-0.55, 0.55) * inner
            rr = rng.uniform(0.12, 0.3) * inner
            start = rng.uniform(0, 360)
            draw.arc(
                (cx + ox - rr, cy + oy - rr, cx + ox + rr, cy + oy + rr),
                start,
                start + rng.uniform(120, 260),
                fill=rng.choice((primary, _shade(primary, -0.08), _shade(primary, 0.12))),
                width=int(r * 0.03),
            )
        _blob(draw, rng, cx, cy, inner * 0.38, secondary, 12)
        _scatter(
            draw, rng, cx, cy, inner * 0.3, 14, (r * 0.02, r * 0.04), (_shade(secondary, -0.2),)
        )
        for _ in range(4):
            _leaf(
                draw,
                cx + rng.uniform(-0.25, 0.25) * inner,
                cy + rng.uniform(-0.25, 0.25) * inner,
                r * 0.07,
                rng.uniform(0, math.pi),
                accent,
            )
        _scatter(draw, rng, cx, cy, inner * 0.45, 30, (r * 0.006, r * 0.012), ((250, 246, 230),))
    elif motif == "roast":
        draw.ellipse(
            (cx - inner * 0.55, cy - inner * 0.42, cx + inner * 0.35, cy + inner * 0.38),
            fill=primary,
        )
        draw.ellipse(
            (cx - inner * 0.45, cy - inner * 0.34, cx + inner * 0.1, cy + inner * 0.05),
            fill=_shade(primary, 0.22),
        )
        draw.ellipse(
            (cx + inner * 0.22, cy - inner * 0.1, cx + inner * 0.5, cy + inner * 0.12),
            fill=_shade(primary, -0.12),
        )
        for _ in range(6):
            x, y = cx + rng.uniform(0.15, 0.6) * inner, cy + rng.uniform(0.1, 0.6) * inner
            s = r * rng.uniform(0.07, 0.1)
            draw.ellipse((x - s, y - s * 0.8, x + s, y + s * 0.8), fill=secondary)
        for _ in range(5):
            x, y = cx + rng.uniform(-0.6, -0.1) * inner, cy + rng.uniform(0.35, 0.6) * inner
            angle = rng.uniform(-0.6, 0.6)
            draw.line(
                (x, y, x + math.cos(angle) * r * 0.22, y + math.sin(angle) * r * 0.22),
                fill=accent,
                width=int(r * 0.055),
            )
        for _ in range(4):
            _leaf(
                draw,
                cx + rng.uniform(-0.3, 0.1) * inner,
                cy + rng.uniform(-0.25, 0.1) * inner,
                r * 0.05,
                rng.uniform(0, math.pi),
                (86, 130, 60),
            )
    elif motif == "plate":
        draw.ellipse(
            (cx - inner * 0.75, cy - inner * 0.45, cx + inner * 0.25, cy + inner * 0.05),
            fill=primary,
        )
        _scatter(
            draw,
            rng,
            cx - inner * 0.25,
            cy - inner * 0.2,
            inner * 0.3,
            20,
            (r * 0.015, r * 0.03),
            (_shade(primary, -0.15),),
        )
        for _ in range(12):
            x, y = cx + rng.uniform(0.05, 0.6) * inner, cy + rng.uniform(-0.55, 0.2) * inner
            angle = rng.uniform(0, math.pi)
            dx, dy = math.cos(angle) * r * 0.16, math.sin(angle) * r * 0.16
            draw.line((x - dx, y - dy, x + dx, y + dy), fill=secondary, width=int(r * 0.06))
        _scatter(
            draw,
            rng,
            cx - inner * 0.1,
            cy + inner * 0.42,
            inner * 0.28,
            40,
            (r * 0.025, r * 0.035),
            (accent, _shade(accent, -0.1)),
        )
        draw.pieslice(
            (cx + inner * 0.3, cy + inner * 0.15, cx + inner * 0.75, cy + inner * 0.6),
            180,
            360,
            fill=(246, 214, 72),
        )
    elif motif in {"wrap", "tacos"}:
        for k in range(3):
            ox = (k - 1) * inner * 0.55
            box = (
                cx + ox - inner * 0.32,
                cy - inner * 0.45,
                cx + ox + inner * 0.32,
                cy + inner * 0.55,
            )
            draw.pieslice(
                box, 180, 360, fill=primary
            ) if motif == "tacos" else draw.rounded_rectangle(
                (box[0], box[1] + inner * 0.2, box[2], box[3]), radius=inner * 0.25, fill=primary
            )
            _scatter(
                draw,
                rng,
                cx + ox,
                cy - inner * 0.1,
                inner * 0.18,
                14,
                (r * 0.03, r * 0.05),
                (secondary, accent, _shade(secondary, 0.2)),
            )
            draw.arc(
                (box[0] + 4, box[1] + inner * 0.05, box[2] - 4, box[3] - inner * 0.05),
                190,
                350,
                fill=_shade(primary, -0.18),
                width=int(r * 0.02),
            )
    elif motif == "salmon":
        draw.rounded_rectangle(
            (cx - inner * 0.6, cy - inner * 0.35, cx + inner * 0.2, cy + inner * 0.12),
            radius=inner * 0.15,
            fill=primary,
        )
        for k in range(5):
            x = cx - inner * 0.5 + k * inner * 0.15
            draw.line(
                (x, cy - inner * 0.3, x + inner * 0.06, cy + inner * 0.08),
                fill=_shade(primary, 0.3),
                width=int(r * 0.012),
            )
        for _ in range(5):
            x, y = cx + rng.uniform(0.25, 0.6) * inner, cy + rng.uniform(-0.5, 0.1) * inner
            _blob(draw, rng, x, y, r * 0.09, secondary, 6)
        for _ in range(5):
            x, y = cx + rng.uniform(-0.55, 0.2) * inner, cy + rng.uniform(0.3, 0.6) * inner
            s = r * 0.08
            draw.ellipse((x - s, y - s * 0.75, x + s, y + s * 0.75), fill=accent)
        draw.ellipse(
            (cx - inner * 0.35, cy - inner * 0.28, cx - inner * 0.15, cy - inner * 0.08),
            fill=(246, 222, 86),
        )
    else:  # omelette
        draw.pieslice(
            (cx - inner * 0.75, cy - inner * 0.65, cx + inner * 0.75, cy + inner * 0.85),
            180,
            360,
            fill=primary,
        )
        draw.arc(
            (cx - inner * 0.75, cy - inner * 0.65, cx + inner * 0.75, cy + inner * 0.85),
            180,
            360,
            fill=_shade(primary, -0.15),
            width=int(r * 0.02),
        )
        _scatter(
            draw, rng, cx, cy - inner * 0.2, inner * 0.35, 12, (r * 0.025, r * 0.045), (secondary,)
        )
        for _ in range(16):
            x, y = cx + rng.uniform(-0.5, 0.5) * inner, cy + rng.uniform(-0.45, 0.05) * inner
            draw.line((x, y, x + r * 0.05, y - r * 0.03), fill=accent, width=int(r * 0.012))
        for _ in range(2):
            x, y = cx + rng.uniform(-0.4, 0.4) * inner, cy + inner * 0.45
            draw.rounded_rectangle(
                (x - r * 0.18, y - r * 0.06, x + r * 0.18, y + r * 0.06),
                radius=r * 0.04,
                fill=(204, 150, 90),
            )


def render_meal_illustration(slug: str, art: MealArt) -> bytes:
    size = (MEAL_SIZE[0] * _SS, MEAL_SIZE[1] * _SS)
    # Deterministic artwork per recipe, not a security use of randomness.
    rng = random.Random(slug)  # noqa: S311
    background = _rgb(art.background)
    canvas = _vertical_gradient(size, _shade(background, 0.35), _shade(background, -0.06)).convert(
        "RGBA"
    )
    draw = ImageDraw.Draw(canvas)
    # A linen napkin and a fork give the plate a sense of place.
    nx, ny = size[0] * 0.06, size[1] * 0.62
    draw.rounded_rectangle(
        (nx, ny, nx + size[0] * 0.17, ny + size[1] * 0.34), radius=18, fill=_shade(background, 0.55)
    )
    for k in range(4):
        y = ny + size[1] * (0.05 + k * 0.08)
        draw.line((nx + 10, y, nx + size[0] * 0.17 - 10, y), fill=_shade(background, 0.2), width=4)
    fx = size[0] * 0.9
    draw.rounded_rectangle(
        (fx - 9, size[1] * 0.25, fx + 9, size[1] * 0.85), radius=9, fill=(188, 186, 180)
    )
    for k in range(4):
        tx = fx - 24 + k * 16
        draw.rounded_rectangle(
            (tx - 4, size[1] * 0.12, tx + 4, size[1] * 0.27), radius=4, fill=(188, 186, 180)
        )
    _food(canvas, art, rng)
    return _png(canvas, MEAL_SIZE)


# --- Vehicles -----------------------------------------------------------------------

VEHICLE_SIZE = (1600, 1000)

# Side profiles as (x, y) fractions of a unit body box: x 0..1 nose-to-tail
# reversed (0 = rear), y 0 = roof line, 1 = sill.
_BODY_PROFILES: dict[str, dict[str, tuple[tuple[float, float], ...]]] = {
    "saloon": {
        "body": (
            (0.0, 0.62),
            (0.03, 0.48),
            (0.16, 0.44),
            (0.3, 0.1),
            (0.42, 0.02),
            (0.66, 0.03),
            (0.8, 0.36),
            (0.97, 0.45),
            (1.0, 0.6),
            (1.0, 0.86),
            (0.0, 0.86),
        ),
        "glass": ((0.2, 0.43), (0.32, 0.14), (0.42, 0.08), (0.64, 0.09), (0.76, 0.38)),
    },
    "suv": {
        "body": (
            (0.0, 0.42),
            (0.03, 0.08),
            (0.08, 0.02),
            (0.62, 0.02),
            (0.76, 0.3),
            (0.96, 0.38),
            (1.0, 0.52),
            (1.0, 0.86),
            (0.0, 0.86),
        ),
        "glass": ((0.06, 0.36), (0.09, 0.09), (0.6, 0.09), (0.72, 0.34)),
    },
    "hatch": {
        "body": (
            (0.0, 0.5),
            (0.02, 0.12),
            (0.08, 0.04),
            (0.6, 0.04),
            (0.74, 0.34),
            (0.95, 0.42),
            (1.0, 0.56),
            (1.0, 0.86),
            (0.0, 0.86),
        ),
        "glass": ((0.06, 0.4), (0.08, 0.13), (0.58, 0.13), (0.7, 0.38)),
    },
}


def render_vehicle_illustration(slug: str, colour_hex: str, body_style: str) -> bytes:
    size = (VEHICLE_SIZE[0] * _SS, VEHICLE_SIZE[1] * _SS)
    w, h = size
    canvas = _vertical_gradient(size, (232, 239, 244), (205, 216, 224)).convert("RGBA")
    draw = ImageDraw.Draw(canvas)
    ground = h * 0.74
    draw.rectangle((0, ground, w, h), fill=(186, 192, 196))
    draw.rectangle((0, ground, w, ground + h * 0.012), fill=(170, 176, 181))
    # A low hedge and house line keep the scene domestic without detail.
    draw.rectangle((0, ground - h * 0.18, w, ground), fill=(215, 222, 214))
    for k in range(int(w / (h * 0.09)) + 1):
        x = k * h * 0.09
        draw.ellipse(
            (x - h * 0.06, ground - h * 0.24, x + h * 0.06, ground - h * 0.12), fill=(150, 176, 140)
        )
    draw.rectangle((0, ground - h * 0.15, w, ground), fill=(160, 184, 148))

    colour = _rgb(colour_hex)
    profile = _BODY_PROFILES.get(body_style, _BODY_PROFILES["saloon"])
    left, right = w * 0.12, w * 0.88
    height = h * (0.36 if body_style == "saloon" else 0.42)
    top = ground - h * 0.05 - height

    def point(fx: float, fy: float) -> tuple[float, float]:
        return (left + (right - left) * fx, top + height * fy)

    _soft_shadow(
        canvas,
        (left - w * 0.02, ground - h * 0.06, right + w * 0.02, ground + h * 0.05),
        110,
        h * 0.02,
    )
    draw = ImageDraw.Draw(canvas)
    body = [point(x, y) for x, y in profile["body"]]
    draw.polygon(body, fill=colour)
    # Lower body shading and a shoulder highlight give it volume.
    draw.polygon(
        [point(0.0, 0.66), point(1.0, 0.66), point(1.0, 0.86), point(0.0, 0.86)],
        fill=_shade(colour, -0.18),
    )
    draw.line([point(0.02, 0.5), point(0.98, 0.5)], fill=_shade(colour, 0.25), width=int(h * 0.006))
    glass = [point(x, y) for x, y in profile["glass"]]
    draw.polygon(glass, fill=(52, 64, 78))
    gx0, gx1 = min(p[0] for p in glass), max(p[0] for p in glass)
    pillar = gx0 + (gx1 - gx0) * 0.5
    draw.line(
        (pillar, min(p[1] for p in glass), pillar, max(p[1] for p in glass)),
        fill=colour,
        width=int(w * 0.008),
    )
    draw.polygon(
        [
            glass[0],
            glass[1],
            (glass[1][0] + w * 0.04, glass[1][1]),
            (glass[0][0] + w * 0.08, glass[0][1]),
        ],
        fill=(92, 110, 128),
    )
    if body_style == "hatch":
        roof = [point(0.08, 0.04), point(0.6, 0.04), point(0.62, 0.08), point(0.06, 0.08)]
        draw.polygon(roof, fill=(240, 240, 238))
    # Lights and door handles.
    draw.rounded_rectangle((*point(0.955, 0.47), *point(1.0, 0.56)), radius=6, fill=(250, 238, 196))
    draw.rounded_rectangle((*point(0.0, 0.5), *point(0.035, 0.6)), radius=6, fill=(196, 52, 46))
    for fx in (0.36, 0.56):
        hx, hy = point(fx, 0.55)
        draw.rounded_rectangle(
            (hx, hy, hx + w * 0.03, hy + h * 0.008), radius=4, fill=_shade(colour, -0.3)
        )
    # Wheels.
    wheel_r = h * 0.1
    for fx in (0.2, 0.8):
        wx, _ = point(fx, 0.86)
        wy = ground - wheel_r * 0.85
        draw.ellipse(
            (wx - wheel_r * 1.12, wy - wheel_r * 1.12, wx + wheel_r * 1.12, wy + wheel_r * 1.12),
            fill=_shade(colour, -0.45),
        )
        draw.ellipse((wx - wheel_r, wy - wheel_r, wx + wheel_r, wy + wheel_r), fill=(34, 36, 40))
        draw.ellipse(
            (wx - wheel_r * 0.62, wy - wheel_r * 0.62, wx + wheel_r * 0.62, wy + wheel_r * 0.62),
            fill=(196, 200, 206),
        )
        for k in range(5):
            angle = k * 2 * math.pi / 5
            draw.line(
                (
                    wx,
                    wy,
                    wx + math.cos(angle) * wheel_r * 0.6,
                    wy + math.sin(angle) * wheel_r * 0.6,
                ),
                fill=(150, 154, 160),
                width=int(wheel_r * 0.14),
            )
        draw.ellipse(
            (wx - wheel_r * 0.14, wy - wheel_r * 0.14, wx + wheel_r * 0.14, wy + wheel_r * 0.14),
            fill=(120, 124, 130),
        )
    return _png(canvas, VEHICLE_SIZE)


# --- Avatars ------------------------------------------------------------------------

AVATAR_SIZE = (512, 512)


def render_avatar_illustration(slug: str, art: AvatarArt) -> bytes:
    size = (AVATAR_SIZE[0] * _SS, AVATAR_SIZE[1] * _SS)
    w, h = size
    canvas = Image.new("RGBA", size, _rgb(art.background) + (255,))
    draw = ImageDraw.Draw(canvas)
    skin, hair, top = _rgb(art.skin), _rgb(art.hair), _rgb(art.top)
    cx, head_cy, head_r = w * 0.5, h * 0.44, w * 0.2
    # Shoulders and neck.
    draw.ellipse((w * 0.16, h * 0.74, w * 0.84, h * 1.3), fill=top)
    draw.rounded_rectangle(
        (cx - head_r * 0.36, head_cy + head_r * 0.6, cx + head_r * 0.36, h * 0.8),
        radius=head_r * 0.2,
        fill=_shade(skin, -0.08),
    )
    # Hair behind the head.
    if art.hair_style == "long":
        draw.rounded_rectangle(
            (
                cx - head_r * 1.2,
                head_cy - head_r * 1.05,
                cx + head_r * 1.2,
                head_cy + head_r * 1.65,
            ),
            radius=head_r * 0.9,
            fill=hair,
        )
    elif art.hair_style == "bob":
        draw.rounded_rectangle(
            (
                cx - head_r * 1.18,
                head_cy - head_r * 1.08,
                cx + head_r * 1.18,
                head_cy + head_r * 0.85,
            ),
            radius=head_r * 0.8,
            fill=hair,
        )
    draw.ellipse(
        (cx - head_r, head_cy - head_r * 1.08, cx + head_r, head_cy + head_r * 1.02), fill=skin
    )
    # Hair on top.
    if art.hair_style == "curly":
        for k in range(11):
            angle = math.pi + k * math.pi / 10
            x, y = (
                cx + math.cos(angle) * head_r * 0.92,
                head_cy - head_r * 0.25 + math.sin(angle) * head_r * 0.88,
            )
            draw.ellipse(
                (x - head_r * 0.3, y - head_r * 0.3, x + head_r * 0.3, y + head_r * 0.3), fill=hair
            )
    elif art.hair_style == "short":
        draw.chord(
            (
                cx - head_r * 1.04,
                head_cy - head_r * 1.2,
                cx + head_r * 1.04,
                head_cy + head_r * 0.35,
            ),
            180,
            360,
            fill=hair,
        )
        draw.rectangle(
            (
                cx - head_r * 1.02,
                head_cy - head_r * 0.45,
                cx - head_r * 0.82,
                head_cy + head_r * 0.05,
            ),
            fill=hair,
        )
        draw.rectangle(
            (
                cx + head_r * 0.82,
                head_cy - head_r * 0.45,
                cx + head_r * 1.02,
                head_cy + head_r * 0.05,
            ),
            fill=hair,
        )
    else:
        draw.chord(
            (
                cx - head_r * 1.08,
                head_cy - head_r * 1.22,
                cx + head_r * 1.08,
                head_cy + head_r * 0.25,
            ),
            180,
            360,
            fill=hair,
        )
        draw.pieslice(
            (
                cx - head_r * 1.1,
                head_cy - head_r * 1.15,
                cx + head_r * 0.4,
                head_cy + head_r * 0.35,
            ),
            180,
            300,
            fill=hair,
        )
    # Face.
    eye_y = head_cy + head_r * 0.08
    for side in (-1, 1):
        ex = cx + side * head_r * 0.38
        draw.ellipse(
            (ex - head_r * 0.08, eye_y - head_r * 0.1, ex + head_r * 0.08, eye_y + head_r * 0.1),
            fill=(52, 40, 34),
        )
        draw.ellipse(
            (ex - head_r * 0.2, eye_y + head_r * 0.22, ex + head_r * 0.06, eye_y + head_r * 0.36),
            fill=_mix(skin, (230, 120, 120), 0.35),
        )
    draw.arc(
        (cx - head_r * 0.32, eye_y + head_r * 0.12, cx + head_r * 0.32, eye_y + head_r * 0.58),
        20,
        160,
        fill=(150, 72, 62),
        width=int(head_r * 0.07),
    )
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).ellipse((0, 0, w, h), fill=255)
    framed = Image.new("RGBA", size, _rgb(art.background) + (255,))
    framed.paste(canvas, (0, 0), mask)
    return _png(framed, AVATAR_SIZE)


ImageRenderer = Callable[[], bytes]
