"""Driveway Vehicle Report PDFs: presenter + WeasyPrint renderer.

The report is built only from the already-authorised, normalised API view the
routers pass in. It never performs a provider lookup, and never reads the VIN,
owner, Home or internal identifiers: the template receives this module's view
model, not the raw payload.

Rendering is locked down: the template is trusted and autoescaped, every
resource is an inline ``data:`` URI built here, and the URL fetcher refuses
everything else (no file, HTTP or redirect), failing the render rather than
silently skipping. Design reference: docs/design/prototypes/vehicle-report/.
"""

from __future__ import annotations

import base64
import io
import re
import unicodedata
from datetime import date, datetime
from functools import lru_cache, partial
from pathlib import Path
from typing import Any, Literal

import anyio
import structlog
from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup
from PIL import Image, UnidentifiedImageError

from mykhaya.config import Settings

log = structlog.get_logger()

ReportFormat = Literal["full", "essential"]
ReportSource = Literal["saved", "lookup"]

_TEMPLATE_DIR = Path(__file__).resolve().parent / "report_templates"
# Where the API image's build copies the brand assets (apps/api/Dockerfile).
_IMAGE_ASSETS_DIR = Path("/opt/mykhaya/report-assets")
# apps/api/mykhaya/<this file> -> apps/web/public when running from a checkout.
_REPO_PUBLIC_DIR = Path(__file__).resolve().parents[2] / "web" / "public"
_FONT_FILES = {
    "figtree_latin": "figtree-latin.woff2",
    "figtree_latin_ext": "figtree-latin-ext.woff2",
    "bricolage_grotesque_latin": "bricolage-grotesque-latin.woff2",
    "bricolage_grotesque_latin_ext": "bricolage-grotesque-latin-ext.woff2",
}
_LOGO_FILE = Path("images") / "marketing" / "mykhaya-logo-256.png"
_PHOTO_MAX_EDGE = 1200
_PHOTO_FORMATS = {"WEBP", "JPEG", "PNG"}
# WeasyPrint is CPU-bound and synchronous: render off the event loop, two at a time.
_RENDER_CONCURRENCY = 2
_render_limiter: anyio.CapacityLimiter | None = None


class VehicleReportUnavailable(RuntimeError):
    """This deployment can't render reports (brand assets missing): fail closed."""


def sanitise_report_filename(registration: str | None, generated: date | None = None) -> str:
    value = re.sub(r"[^A-Za-z0-9]+", "-", (registration or "vehicle").upper()).strip("-")
    return (
        f"MyKhaya-Vehicle-Report-{value or 'vehicle'}-{(generated or date.today()).isoformat()}.pdf"
    )


# --------------------------------------------------------------------------- formatting

_MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
_SHORT_UPPER_WORDS = {"BMW", "MG", "VW", "DS"}


def _as_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def fmt_date(value: Any, precision: str | None = "day") -> str | None:
    d = _as_date(value)
    if d is None:
        return None
    if precision == "year":
        return str(d.year)
    if precision == "month":
        return f"{_MONTHS[d.month - 1]} {d.year}"
    return f"{d.day} {_MONTHS[d.month - 1]} {d.year}"


def fmt_money(value: Any) -> str | None:
    if value is None:
        return None
    amount = float(value)
    return f"£{amount:,.0f}" if amount.is_integer() else f"£{amount:,.2f}"


def fmt_money_pence(value: Any) -> str | None:
    return None if value is None else f"£{float(value):,.2f}"


def _unit(unit: str | None) -> str:
    return "km" if (unit or "").lower() in {"km", "kilometres", "kilometers"} else "mi"


def fmt_miles(value: Any, unit: str | None) -> str | None:
    if value is None:
        return None
    return f"{int(value):,} {_unit(unit)}"


def fmt_engine(value: Any) -> str | None:
    """Engine capacity is a code-like figure: no thousands separator."""
    digits = re.sub(r"\D", "", str(value or ""))
    return f"{int(digits)} cc" if digits and int(digits) > 0 else None


def fmt_title(value: Any) -> str | None:
    """DVLA returns SHOUTING CASE; present make/colour/fuel in title case."""
    if not value:
        return None
    text = str(value).strip()
    if not text.isupper():
        return text
    return " ".join(w if w in _SHORT_UPPER_WORDS else w.capitalize() for w in text.split())


def fmt_sentence(value: Any) -> str | None:
    if not value:
        return None
    text = str(value).strip().lower()
    return text[:1].upper() + text[1:]


def fmt_fuel(value: Any) -> str | None:
    if not value:
        return None
    return {"ELECTRICITY": "Electric"}.get(str(value).strip().upper(), fmt_title(value))


def fmt_cap(value: Any) -> str | None:
    """Capitalise the first letter only (keeps codes like M1/M1G intact)."""
    if not value:
        return None
    text = re.sub(r"(\d{4})-(\d{4})", r"\1–\2", str(value).strip())
    return text[:1].upper() + text[1:]


def fmt_bool(value: Any) -> str | None:
    return None if value is None else ("Yes" if value else "No")


def fmt_tax_year(value: str | None) -> str | None:
    if not value:
        return None
    match = re.fullmatch(r"(\d{4})[-/](\d{2,4})", value)
    return f"{match.group(1)}–{match.group(2)[-2:]}" if match else value


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- view model

_DEFECT_ORDER = ["dangerous", "major", "fail", "minor", "prs", "advisory", "user_entered", "other"]
_DEFECT_LABEL = {
    "dangerous": "Dangerous",
    "major": "Major",
    "fail": "Fail",
    "minor": "Minor",
    "prs": "Repaired at test",
    "advisory": "Advisory",
    "user_entered": "Note",
    "other": "Other",
}
_MOT_STATUS = {
    "valid": ("MOT valid", "good"),
    "expired": ("MOT expired", "bad"),
    "not_yet_due": ("First MOT not yet due", "neutral"),
    "no_record": ("No MOT record found", "neutral"),
}
_TAX_STATUS_TONE = {"taxed": "good", "untaxed": "bad", "sorn": "neutral"}


# Bounded, explicit text handling. HarfBuzz CVE-2023-25193 is quadratic only
# in runs of *stacked combining marks*; ordinary long text renders in linear
# time (measured: 240,000 characters of MOT defects in about 6 s, 141 MB).
# So: (1) runs of combining marks are capped (real text never stacks more than
# a few), which removes the quadratic case without losing legitimate content;
# (2) per-item ceilings far above real DVLA/DVSA values, with a visible marker
# when exceeded, so nothing is ever shortened silently; (3) a whole-report
# budget for MOT defect text, beyond which every test stays listed but its
# detail is replaced by an explicit note.
_MAX_STACKED_MARKS = 4
_MAX_FIELD_CHARS = 300
_MAX_DEFECT_CHARS = 4000
_MAX_REPORT_DEFECT_CHARS = 150_000


def _safe_text(value: object, limit: int) -> str:
    text = unicodedata.normalize("NFC", str(value))
    kept: list[str] = []
    stacked = 0
    for char in text:
        if unicodedata.category(char) in {"Mn", "Me"}:
            stacked += 1
            if stacked > _MAX_STACKED_MARKS:
                continue
        else:
            stacked = 0
        kept.append(char)
    text = "".join(kept)
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()} … [shortened from {len(text):,} characters]"


def _rows(pairs: list[tuple[str, str | None]]) -> list[dict[str, str]]:
    return [
        {"label": label, "value": _safe_text(value, _MAX_FIELD_CHARS)}
        for label, value in pairs
        if value
    ]


def _result(value: str | None) -> tuple[str, str]:
    v = (value or "").lower()
    if v in {"passed", "pass"}:
        return "Passed", "good"
    if v in {"failed", "fail"}:
        return "Failed", "bad"
    return (v.replace("_", " ").capitalize() or "Unknown"), "neutral"


def _ved_context(tax: dict[str, Any]) -> dict[str, Any] | None:
    if tax.get("annual_rate") is None:
        return None
    options = tax.get("payment_options") or {}
    plans = []
    if "monthly_direct_debit_per_month" in options:
        plans.append(
            {
                "label": "Monthly (12 payments)",
                "amount": f"{fmt_money_pence(options['monthly_direct_debit_per_month'])} / month",
                "total": fmt_money(options.get("monthly_direct_debit_total")),
            }
        )
    if "six_month_direct_debit_payment" in options:
        plans.append(
            {
                "label": "6-monthly (2 payments)",
                "amount": (
                    f"{fmt_money_pence(options['six_month_direct_debit_payment'])} / 6 months"
                ),
                "total": fmt_money(options.get("six_month_direct_debit_total")),
            }
        )
    if "six_month_single_payment" in options:
        plans.append(
            {
                "label": "6-monthly (single payment)",
                "amount": fmt_money_pence(options["six_month_single_payment"]),
                "total": None,
            }
        )
    basis = {"conditional_estimate": "standard rate", "calculated": "published rate"}.get(
        tax.get("status") or "", "estimate"
    )
    tax_year = fmt_tax_year(tax.get("tax_year"))
    return {
        "annual": fmt_money(tax["annual_rate"]),
        "basis": f"{tax_year or ''} {basis}".strip(),
        "plans": plans,
        "category": fmt_cap(tax.get("category")),
        "tax_year": tax_year,
        "assumptions": [fmt_cap(a) for a in tax.get("assumptions") or []],
        "missing": [fmt_cap(a) for a in tax.get("missing_information") or []],
        "supplement": tax.get("supplement_message"),
    }


def _mot_context(mot: dict[str, Any] | None) -> dict[str, Any]:
    # Saved vehicles carry {"summary": {...}, "tests": [...]}; one-off
    # lookups carry the status fields at the top level.
    summary = (mot or {}).get("summary") or mot or {}
    raw_tests = (mot or {}).get("tests") or []
    tests: list[dict[str, Any]] = []
    budget = _MAX_REPORT_DEFECT_CHARS
    for index, test in enumerate(raw_tests):
        label, tone = _result(test.get("result"))
        defects = sorted(
            test.get("defects") or [],
            key=lambda d: (
                _DEFECT_ORDER.index(d.get("category"))
                if d.get("category") in _DEFECT_ORDER
                else len(_DEFECT_ORDER)
            ),
        )
        previous = raw_tests[index + 1] if index + 1 < len(raw_tests) else None
        delta = None
        current_miles = _int_or_none(test.get("odometer_value"))
        previous_miles = _int_or_none((previous or {}).get("odometer_value"))
        if current_miles is not None and previous_miles is not None:
            diff = current_miles - previous_miles
            if diff > 0:
                delta = f"+{diff:,} {_unit(test.get('odometer_unit'))}"
        rendered = [
            {
                "label": _DEFECT_LABEL.get(d.get("category"), "Other"),
                "kind": d.get("category") if d.get("category") in _DEFECT_LABEL else "other",
                "text": _safe_text(d.get("text") or "", _MAX_DEFECT_CHARS),
            }
            for d in defects
        ]
        size = sum(len(d["text"]) for d in rendered)
        omitted = 0
        if size > budget:
            # Report length limit reached: keep the test, state what's left out.
            omitted, rendered = len(rendered), []
        else:
            budget -= size
        tests.append(
            {
                "date": fmt_date(test.get("test_date")),
                "result": label,
                "tone": tone,
                "mileage": fmt_miles(current_miles, test.get("odometer_unit")) or "Not recorded",
                "delta": delta,
                "expiry": fmt_date(test.get("expiry_date")),
                "defects": rendered,
                "defects_omitted": omitted,
            }
        )
    status_label, status_tone = _MOT_STATUS.get(summary.get("status") or "", (None, "neutral"))
    return {
        "available": bool(tests) or bool(status_label),
        "status": status_label,
        "tone": status_tone,
        "expiry": fmt_date(summary.get("expiry_date") or summary.get("due_date")),
        "recent": tests[:3],
        "tests": tests,
        "count": len(tests),
        "passed": sum(1 for t in tests if t["tone"] == "good"),
        "failed": sum(1 for t in tests if t["tone"] == "bad"),
        "defect_count": sum(len(t["defects"]) + t["defects_omitted"] for t in tests),
        "tests_with_omitted_detail": sum(1 for t in tests if t["defects_omitted"]),
        "latest_mileage": next(
            (t["mileage"] for t in tests if t["mileage"] != "Not recorded"), None
        ),
        "checked": fmt_date(summary.get("refreshed_at")),
    }


def build_report_context(
    *,
    vehicle: dict[str, Any],
    mot: dict[str, Any] | None,
    format: ReportFormat,
    source: ReportSource,
    generated_at: datetime,
    photo_uri: str | None = None,
    include_household_details: bool = True,
) -> dict[str, Any]:
    """The template's view model. Only the fields listed here can ever reach
    the PDF; VIN, owner, Home and internal identifiers are never read."""
    full = format == "full"
    make, model = fmt_title(vehicle.get("make")), vehicle.get("model")
    fuel = fmt_fuel(vehicle.get("fuel_type"))
    # Household-entered details only ever come from a saved vehicle, and only
    # when the requester hasn't asked for a report without them.
    household = source == "saved" and include_household_details
    nickname = (vehicle.get("nickname") or "").strip() if household else ""
    photo_uri = photo_uri if household else None

    if make or model:
        name = " ".join(v for v in (make, model) if v)
        nickname_chip = nickname or None
        subtitle = (
            "Household vehicle summary"
            if source == "saved"
            else ("Vehicle summary from a one-off registration lookup")
        )
    elif nickname:
        name, nickname_chip = nickname, None
        subtitle = "Nickname added by your household"
    else:
        name, nickname_chip = "Your vehicle", None
        subtitle = (
            "Household vehicle summary"
            if source == "saved"
            else ("Vehicle summary from a one-off registration lookup")
        )

    household_bits = [
        label for label, present in (("nickname", nickname), ("photo", photo_uri)) if present
    ]
    household_note = (
        f"The {' and '.join(household_bits)} {'was' if len(household_bits) == 1 else 'were'} "
        "added by your household, not provided by DVLA or DVSA."
        if household_bits
        else None
    )

    tax_status = vehicle.get("tax_status")
    revenue_weight = _int_or_none(vehicle.get("revenue_weight"))
    co2 = _int_or_none(vehicle.get("co2_emissions"))
    additional = _rows(
        [
            (
                Markup("CO<sub>2</sub> emissions"),
                f"{co2} g/km" if co2 is not None else None,
            ),
            ("Euro status", vehicle.get("euro_status")),
            ("Type approval", vehicle.get("type_approval")),
            ("Wheelplan", fmt_sentence(vehicle.get("wheel_plan"))),
            ("Marked for export", fmt_bool(vehicle.get("marked_for_export"))),
        ]
    )
    # The Full report's page-1 card has room for seven rows: the core DVLA
    # fields first, then the commonest extras. Anything left over flows into a
    # "More DVLA details" card after the MOT history.
    extras = _rows(
        [
            ("Marked as scrapped", fmt_bool(vehicle.get("marked_as_scrapped"))),
            ("Latest V5C issued", fmt_date(vehicle.get("date_of_last_v5c_issued"))),
            ("Revenue weight", f"{revenue_weight:,} kg" if revenue_weight else None),
            ("Vehicle status", vehicle.get("vehicle_status")),
            (
                "First registered with DVLA",
                fmt_date(
                    vehicle.get("first_registration_with_dvla_date"),
                    vehicle.get("first_registration_with_dvla_precision"),
                ),
            ),
            ("Real driving emissions", vehicle.get("real_driving_emissions")),
            ("Automated vehicle", fmt_bool(vehicle.get("automated_vehicle"))),
            ("ART end date", fmt_date(vehicle.get("art_end_date"))),
        ]
    )
    room = max(0, 7 - len(additional))

    return {
        "full": full,
        "source": source,
        "report_kind": "Full report" if full else "Essential report",
        "eyebrow": "Saved Home vehicle" if source == "saved" else "One-off lookup",
        "subtitle": subtitle,
        "name": _safe_text(name, _MAX_FIELD_CHARS),
        "registration": _safe_text(vehicle.get("registration") or "No registration", 40),
        "nickname": _safe_text(nickname_chip, _MAX_FIELD_CHARS) if nickname_chip else None,
        "chips": [fuel] if fuel and not nickname_chip else [],
        "photo_uri": photo_uri,
        "household_note": household_note,
        "generated": fmt_date(generated_at),
        "details": _rows(
            [
                ("Make / model", name if (make or model) else None),
                ("Year", str(vehicle["year"]) if vehicle.get("year") else None),
                (
                    "First registration",
                    fmt_date(
                        vehicle.get("first_registration_date"),
                        vehicle.get("first_registration_precision"),
                    ),
                ),
                ("Fuel", fuel),
                ("Colour", fmt_title(vehicle.get("colour"))),
                ("Engine capacity", fmt_engine(vehicle.get("engine_size"))),
            ]
        ),
        "tax_status": tax_status,
        "tax_tone": _TAX_STATUS_TONE.get((tax_status or "").lower(), "neutral"),
        "tax_rows": _rows(
            [
                ("Tax status", tax_status),
                ("Tax due", fmt_date(vehicle.get("tax_due_date"))),
            ]
        ),
        "ved": _ved_context(vehicle.get("tax_calculation") or {}),
        "additional": additional + extras[:room] if full else additional,
        "more_dvla": extras[room:],
        "dvla_checked": fmt_date(
            vehicle.get("last_successful_lookup") or vehicle.get("checked_at")
        ),
        "mot": _mot_context(mot),
    }


# --------------------------------------------------------------------------- assets


def _data_uri(data: bytes, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def _assets_root(settings: Settings | None) -> Path:
    configured = Path(settings.vehicle_report_assets_dir) if settings else None
    for candidate in (configured, _IMAGE_ASSETS_DIR, _REPO_PUBLIC_DIR):
        if candidate is not None and (candidate / _LOGO_FILE).is_file():
            return candidate
    raise VehicleReportUnavailable("Vehicle report brand assets are missing from this deployment.")


@lru_cache(maxsize=4)
def _static_assets(root: str) -> tuple[str, str]:
    """(stylesheet with embedded fonts, logo data URI) for an asset root."""
    base = Path(root)
    css = (_TEMPLATE_DIR / "vehicle_report.css").read_text(encoding="utf-8")
    for key, filename in _FONT_FILES.items():
        font = (base / "fonts" / "marketing" / filename).read_bytes()
        # Replace the whole quoted token: a bare "FONT:figtree_latin" prefix
        # would also corrupt "FONT:figtree_latin_ext".
        token = f'url("FONT:{key}")'
        if token not in css:
            raise VehicleReportUnavailable(f"Vehicle report stylesheet has no {key} font slot.")
        css = css.replace(token, f'url("{_data_uri(font, "font/woff2")}")')
    logo = _data_uri((base / _LOGO_FILE).read_bytes(), "image/png")
    return css, logo


@lru_cache(maxsize=1)
def _environment() -> Environment:
    return Environment(
        loader=FileSystemLoader(_TEMPLATE_DIR),
        autoescape=select_autoescape(["html", "j2"], default=True),
    )


def prepare_report_photo(data: bytes | None) -> str | None:
    """Re-validate a stored vehicle photo and re-encode it as a bounded JPEG
    data URI. Anything that isn't a WebP/JPEG/PNG image falls back to the
    no-photo state rather than reaching the renderer."""
    if not data:
        return None
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in _PHOTO_FORMATS:
                return None
            image.thumbnail((_PHOTO_MAX_EDGE, _PHOTO_MAX_EDGE))
            buffer = io.BytesIO()
            image.convert("RGB").save(buffer, format="JPEG", quality=85, optimize=True)
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        log.warning("vehicle_report_photo_skipped")
        return None
    return _data_uri(buffer.getvalue(), "image/jpeg")


# --------------------------------------------------------------------------- rendering


def render_vehicle_report_html(context: dict[str, Any], settings: Settings | None = None) -> str:
    css, logo = _static_assets(str(_assets_root(settings)))
    template = _environment().get_template("vehicle_report.html.j2")
    return template.render(css=css, logo=logo, **context)


def _url_fetcher() -> Any:
    from weasyprint.urls import URLFetcher

    # Only inline data: URIs may load. No file, HTTP or redirect is ever
    # followed, and a refused resource fails the render (fail_on_errors).
    return URLFetcher(
        allowed_protocols={"data"}, allow_redirects=False, fail_on_errors=True, timeout=1
    )


def build_vehicle_report_pdf(
    *,
    vehicle: dict[str, Any],
    mot: dict[str, Any] | None,
    format: ReportFormat,
    generated_at: datetime,
    source: ReportSource = "saved",
    photo: bytes | None = None,
    include_household_details: bool = True,
    settings: Settings | None = None,
) -> bytes:
    """Render the approved Vehicle Report design to A4 PDF bytes (synchronous;
    use :func:`render_vehicle_report_pdf` from request handlers)."""
    from weasyprint import HTML

    context = build_report_context(
        vehicle=vehicle,
        mot=mot,
        format=format,
        source=source,
        generated_at=generated_at,
        photo_uri=prepare_report_photo(photo)
        if source == "saved" and include_household_details
        else None,
        include_household_details=include_household_details,
    )
    html = render_vehicle_report_html(context, settings)
    # presentational_hints stays off: HTML attributes never become CSS.
    pdf: bytes = HTML(string=html, url_fetcher=_url_fetcher()).write_pdf(presentational_hints=False)
    return pdf


async def render_vehicle_report_pdf(**kwargs: Any) -> bytes:
    """Render on a worker thread, at most two at a time, so a report never
    stalls the API's event loop."""
    global _render_limiter
    if _render_limiter is None:
        _render_limiter = anyio.CapacityLimiter(_RENDER_CONCURRENCY)
    return await anyio.to_thread.run_sync(
        partial(build_vehicle_report_pdf, **kwargs), limiter=_render_limiter
    )
