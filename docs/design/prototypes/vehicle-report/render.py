"""Render the Vehicle Report prototype to HTML, PDF and per-page PNG previews.

Design-stage QA tool only: it is not wired to the API. Run it inside the
renderer container (see README.md) so fonts and layout match the API runtime
base image.

    python render.py OUTPUT_DIR
"""

from __future__ import annotations

import base64
import mimetypes
import os
import re
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup
from weasyprint import HTML
from weasyprint.urls import URLFetcher

from scenarios import GENERATED_AT, SCENARIOS

HERE = Path(__file__).resolve().parent
# Official brand assets are read from apps/web/public (mounted at /brand) so the
# prototype never carries its own copies of the logo or fonts.
BRAND = Path(os.environ.get("REPORT_BRAND_DIR", "/brand"))
# Sample photos are never kept in the (public) repository: mount them at
# /photos (or set REPORT_PHOTO_DIR). A missing photo renders the no-photo state.
PHOTOS = Path(os.environ.get("REPORT_PHOTO_DIR", "/photos"))

# --------------------------------------------------------------------------- formatting

_MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()


def _as_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()


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


def fmt_miles(value: Any, unit: str | None) -> str | None:
    if value is None:
        return None
    return f"{int(value):,} {'km' if unit == 'km' else 'mi'}"


def fmt_engine(value: Any) -> str | None:
    digits = re.sub(r"\D", "", str(value or ""))
    return f"{int(digits)} cc" if digits else None  # capacity is a code-like figure: no separator


def fmt_title(value: Any) -> str | None:
    """DVLA returns SHOUTING CASE; present make/colour/fuel in title case."""
    if not value:
        return None
    text = str(value).strip()
    if not text.isupper():
        return text
    return " ".join(w if len(w) <= 3 and w.isalpha() and w in {"BMW", "MG", "VW", "DS"} else w.capitalize()
                    for w in text.split())


def fmt_sentence(value: Any) -> str | None:
    if not value:
        return None
    text = str(value).strip().lower()
    return text[:1].upper() + text[1:]


def fmt_fuel(value: Any) -> str | None:
    if not value:
        return None
    return {"ELECTRICITY": "Electric"}.get(str(value).upper(), fmt_title(value))


def fmt_cap(value: Any) -> str | None:
    """Capitalise the first letter only; keeps codes like M1/M1G intact."""
    if not value:
        return None
    text = re.sub(r"(\d{4})-(\d{4})", r"\1–\2", str(value).strip())
    return text[:1].upper() + text[1:]


def fmt_bool(value: Any) -> str | None:
    return None if value is None else ("Yes" if value else "No")


def fmt_tax_year(value: str | None) -> str | None:
    if not value:
        return None
    m = re.fullmatch(r"(\d{4})-(\d{4})", value)
    return f"{m.group(1)}–{m.group(2)[2:]}" if m else value


# --------------------------------------------------------------------------- view model

_DEFECT_ORDER = ["dangerous", "major", "fail", "minor", "prs", "advisory", "user_entered", "other"]
_DEFECT_LABEL = {
    "dangerous": "Dangerous", "major": "Major", "fail": "Fail", "minor": "Minor",
    "prs": "Repaired at test", "advisory": "Advisory", "user_entered": "Note", "other": "Other",
}

_MOT_STATUS = {
    "valid": ("MOT valid", "good"),
    "expired": ("MOT expired", "bad"),
    "not_yet_due": ("First MOT not yet due", "neutral"),
    "no_record": ("No MOT record found", "neutral"),
}

_TAX_STATUS_TONE = {"taxed": "good", "untaxed": "bad", "sorn": "neutral"}


def _rows(pairs: list[tuple[str, str | None]]) -> list[dict[str, str]]:
    return [{"label": k, "value": v} for k, v in pairs if v not in (None, "")]


def _result(value: str | None) -> tuple[str, str]:
    v = (value or "").lower()
    if v in {"passed", "pass"}:
        return "Passed", "good"
    if v in {"failed", "fail"}:
        return "Failed", "bad"
    return (v.replace("_", " ").capitalize() or "Unknown"), "neutral"


def build_context(*, vehicle: dict, mot: dict | None, fmt: str, source: str,
                  photo_uri: str | None, generated_at: str) -> dict[str, Any]:
    full = fmt == "full"
    make, model = fmt_title(vehicle.get("make")), vehicle.get("model")
    name = " ".join(v for v in (make, model) if v) or vehicle.get("nickname") or "Your vehicle"
    fuel = fmt_fuel(vehicle.get("fuel_type"))

    tax = vehicle.get("tax_calculation") or {}
    options = tax.get("payment_options") or {}
    ved = None
    if tax.get("annual_rate") is not None:
        plans = []
        if "monthly_direct_debit_per_month" in options:
            plans.append({"label": "Monthly (12 payments)",
                          "amount": f"{fmt_money_pence(options['monthly_direct_debit_per_month'])} / month",
                          "total": fmt_money(options.get("monthly_direct_debit_total"))})
        if "six_month_direct_debit_payment" in options:
            plans.append({"label": "6-monthly (2 payments)",
                          "amount": f"{fmt_money_pence(options['six_month_direct_debit_payment'])} / 6 months",
                          "total": fmt_money(options.get("six_month_direct_debit_total"))})
        if "six_month_single_payment" in options:
            plans.append({"label": "6-monthly (single payment)",
                          "amount": fmt_money_pence(options["six_month_single_payment"]),
                          "total": None})
        basis = {"conditional_estimate": "standard rate", "calculated": "published rate"}.get(tax.get("status"), "estimate")
        ved = {
            "annual": fmt_money(tax["annual_rate"]),
            "basis": f"{fmt_tax_year(tax.get('tax_year'))} {basis}".strip(),
            "plans": plans,
            "category": fmt_cap(tax.get("category")),
            "tax_year": fmt_tax_year(tax.get("tax_year")),
            "assumptions": [fmt_cap(a) for a in tax.get("assumptions") or []],
            "missing": [fmt_cap(a) for a in tax.get("missing_information") or []],
            "supplement": tax.get("supplement_message"),
        }

    tax_status = vehicle.get("tax_status")
    tax_rows = _rows([
        ("Tax status", tax_status),
        ("Tax due", fmt_date(vehicle.get("tax_due_date"))),
    ])

    details = _rows([
        ("Make / model", name if (make or model) else None),
        ("Year", str(vehicle["year"]) if vehicle.get("year") else None),
        ("First registration", fmt_date(vehicle.get("first_registration_date"),
                                        vehicle.get("first_registration_precision"))),
        ("Fuel", fuel),
        ("Colour", fmt_title(vehicle.get("colour"))),
        ("Engine capacity", fmt_engine(vehicle.get("engine_size"))),
    ])

    additional = _rows([
        (Markup("CO<sub>2</sub> emissions"), f"{vehicle['co2_emissions']} g/km" if vehicle.get("co2_emissions") is not None else None),
        ("Euro status", vehicle.get("euro_status")),
        ("Type approval", vehicle.get("type_approval")),
        ("Wheelplan", fmt_sentence(vehicle.get("wheel_plan"))),
        ("Marked for export", fmt_bool(vehicle.get("marked_for_export"))),
    ])

    # The Full report's page-1 card has room for seven rows: the core DVLA
    # fields first, then the commonest extras. Anything left over flows into a
    # "More DVLA details" card after the MOT history.
    extras = _rows([
        ("Marked as scrapped", fmt_bool(vehicle.get("marked_as_scrapped"))),
        ("Latest V5C issued", fmt_date(vehicle.get("date_of_last_v5c_issued"))),
        ("Revenue weight", f"{vehicle['revenue_weight']:,} kg" if vehicle.get("revenue_weight") else None),
        ("Vehicle status", vehicle.get("vehicle_status")),
        ("First registered with DVLA", fmt_date(vehicle.get("first_registration_with_dvla_date"),
                                                vehicle.get("first_registration_with_dvla_precision"))),
        ("Real driving emissions", vehicle.get("real_driving_emissions")),
        ("Automated vehicle", fmt_bool(vehicle.get("automated_vehicle"))),
        ("ART end date", fmt_date(vehicle.get("art_end_date"))),
    ])
    room = max(0, 7 - len(additional))
    additional_full, more_dvla = additional + extras[:room], extras[room:]

    # MOT
    summary = (mot or {}).get("summary") or {}
    raw_tests = (mot or {}).get("tests") or []
    tests = []
    for index, t in enumerate(raw_tests):
        label, tone = _result(t.get("result"))
        defects = sorted(t.get("defects") or [], key=lambda d: _DEFECT_ORDER.index(d.get("category", "other"))
                         if d.get("category") in _DEFECT_ORDER else 99)
        prev = raw_tests[index + 1] if index + 1 < len(raw_tests) else None
        delta = None
        if prev and t.get("odometer_value") is not None and prev.get("odometer_value") is not None:
            diff = t["odometer_value"] - prev["odometer_value"]
            if diff > 0:
                delta = f"+{diff:,} {'km' if t.get('odometer_unit') == 'km' else 'mi'}"
        tests.append({
            "date": fmt_date(t.get("test_date")),
            "result": label,
            "tone": tone,
            "mileage": fmt_miles(t.get("odometer_value"), t.get("odometer_unit")) or "Not recorded",
            "delta": delta,
            "expiry": fmt_date(t.get("expiry_date")),
            "defects": [{"label": _DEFECT_LABEL.get(d.get("category"), "Other"),
                         "kind": d.get("category") if d.get("category") in _DEFECT_LABEL else "other",
                         "text": d.get("text") or ""} for d in defects],
        })
    status_label, status_tone = _MOT_STATUS.get(summary.get("status") or "", (None, "neutral"))
    mot_ctx = {
        "available": bool(tests) or bool(status_label),
        "status": status_label,
        "tone": status_tone,
        "expiry": fmt_date(summary.get("expiry_date") or summary.get("due_date")),
        "recent": tests[:3],
        "tests": tests,
        "count": len(tests),
        "passed": sum(1 for t in tests if t["tone"] == "good"),
        "failed": sum(1 for t in tests if t["tone"] == "bad"),
        "defect_count": sum(len(t["defects"]) for t in tests),
        "latest_mileage": next((t["mileage"] for t in tests if t["mileage"] != "Not recorded"), None),
        "checked": fmt_date(summary.get("refreshed_at")),
    }
    dvla_checked = fmt_date(vehicle.get("last_successful_lookup"))

    hero_chips = []
    if source == "saved" and vehicle.get("nickname") and (make or model):
        hero_chips.append(vehicle["nickname"])
    elif fuel:
        hero_chips.append(fuel)

    return {
        "full": full,
        "source": source,
        "report_kind": "Full report" if full else "Essential report",
        "eyebrow": "Saved Home vehicle" if source == "saved" else "One-off lookup",
        "subtitle": ("Household vehicle summary" if source == "saved"
                     else "Vehicle summary from a one-off registration lookup"),
        "name": name,
        "registration": vehicle.get("registration") or "No registration",
        "chips": hero_chips,
        "photo_uri": photo_uri,
        "generated": fmt_date(generated_at),
        "details": details,
        "tax_status": tax_status,
        "tax_tone": _TAX_STATUS_TONE.get((tax_status or "").lower(), "neutral"),
        "tax_rows": tax_rows,
        "ved": ved,
        "additional": additional_full if full else additional,
        "more_dvla": more_dvla,
        "dvla_checked": dvla_checked,
        "mot": mot_ctx,
    }


# --------------------------------------------------------------------------- rendering

def data_uri(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "font/woff2"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


# Only inline data: URIs may load (WeasyPrint >= 70). No file, HTTP or redirect
# is ever followed, and a blocked resource fails the render rather than being
# silently dropped, so a template mistake can't produce SSRF or a file read.
deny_fetcher = URLFetcher(allowed_protocols={"data"}, allow_redirects=False,
                          fail_on_errors=True, timeout=1)


def main(out_dir: str) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    env = Environment(loader=FileSystemLoader(HERE), autoescape=select_autoescape(["html", "j2"]))
    template = env.get_template("vehicle-report.html.j2")
    css = (HERE / "vehicle-report.css").read_text(encoding="utf-8")
    fonts = {p.stem.replace("-", "_"): data_uri(p) for p in (BRAND / "fonts" / "marketing").glob("*.woff2")}
    for key, uri in fonts.items():
        css = css.replace(f'url("FONT:{key}")', f'url("{uri}")')  # whole token, not a prefix
    logo = data_uri(BRAND / "images" / "marketing" / "mykhaya-logo-256.png")

    manifest = []
    for slug, title, fmt, source, vehicle, mot, photo in SCENARIOS:
        ctx = build_context(vehicle=vehicle, mot=mot, fmt=fmt, source=source,
                            photo_uri=data_uri(PHOTOS / photo) if photo and (PHOTOS / photo).is_file() else None,
                            generated_at=GENERATED_AT)
        html = template.render(css=css, logo=logo, **ctx)
        (out / f"{slug}.html").write_text(html, encoding="utf-8")
        pdf_path = out / f"{slug}.pdf"
        HTML(string=html, url_fetcher=deny_fetcher).write_pdf(pdf_path)
        for old in out.glob(f"{slug}-p*.png"):
            old.unlink()
        subprocess.run(["pdftoppm", "-png", "-r", "110", str(pdf_path), str(out / f"{slug}-p")], check=True)
        pages = sorted(p.name for p in out.glob(f"{slug}-p*.png"))
        manifest.append((slug, title, pages))
        print(f"{slug}: {len(pages)} page(s)")
    (out / "manifest.txt").write_text(
        "\n".join(f"{s}|{t}|{','.join(p)}" for s, t, p in manifest), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1])
