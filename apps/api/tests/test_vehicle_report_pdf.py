"""Vehicle Report presenter, template and PDF rendering (no database).

Content assertions run against the rendered HTML (the PDF's text is
compressed); PDF-level tests cover pagination, fonts, determinism and the
locked-down resource fetcher."""

from __future__ import annotations

import io
from datetime import UTC, datetime
from typing import Any

import pytest
from PIL import Image

from mykhaya.vehicle_report_pdf import (
    _url_fetcher,
    build_report_context,
    build_vehicle_report_pdf,
    prepare_report_photo,
    render_vehicle_report_html,
    sanitise_report_filename,
)

GENERATED = datetime(2026, 11, 17, 9, 12, tzinfo=UTC)
VIN = "WBA8E1C55JA000001"
OWNER_ID = "6a4c1f0e-0000-4000-8000-00000000beef"
HOME_ID = "6a4c1f0e-0000-4000-8000-00000000cafe"


def saved_vehicle(**overrides: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "id": "6a4c1f0e-0000-4000-8000-000000000001",
        "group_id": HOME_ID,
        "owner_user_id": OWNER_ID,
        "vin": VIN,
        "nickname": "Pebble",
        "make": "PEUGEOT",
        "model": "e-208",
        "colour": "GREY",
        "year": 2021,
        "fuel_type": "ELECTRICITY",
        "engine_size": None,
        "registration": "MK21 HYA",
        "first_registration_date": "2021-03-01",
        "first_registration_precision": "month",
        "tax_status": "Taxed",
        "tax_due_date": "2027-03-01",
        "co2_emissions": 0,
        "type_approval": "M1",
        "wheel_plan": "2 AXLE RIGID BODY",
        "revenue_weight": 1980,
        "marked_for_export": False,
        "marked_as_scrapped": False,
        "date_of_last_v5c_issued": "2024-06-12",
        "last_successful_lookup": "2026-11-17T08:30:00+00:00",
        "tax_calculation": {
            "status": "conditional_estimate",
            "annual_rate": 200,
            "payment_options": {
                "single_12_month_total": 200.0,
                "monthly_direct_debit_per_month": 17.5,
                "monthly_direct_debit_total": 210.0,
                "six_month_direct_debit_payment": 105.0,
                "six_month_direct_debit_total": 210.0,
                "six_month_single_payment": 110.0,
                "six_month_single_total": 220.0,
            },
            "tax_year": "2026-2027",
            "category": "post-2017 car",
            "assumptions": ["base subsequent-licence rate is £200"],
            "missing_information": ["original list price"],
        },
    }
    value.update(overrides)
    return value


def saved_mot(tests: int = 3) -> dict[str, Any]:
    history = [
        {
            "test_date": f"{2026 - i}-03-15",
            "result": "failed" if i == 1 else "passed",
            "odometer_value": 30599 - i * 9000,
            "odometer_unit": "mi",
            "expiry_date": None if i == 1 else f"{2027 - i}-03-14",
            "defects": [
                {
                    "category": "advisory",
                    "text": "Nearside front tyre worn close to legal limit",
                    "dangerous": False,
                },
                {"category": "dangerous", "text": "Brake hose damaged", "dangerous": True},
            ]
            if i == 1
            else [],
        }
        for i in range(tests)
    ]
    return {
        "summary": {
            "status": "valid",
            "expiry_date": "2027-03-14",
            "refreshed_at": "2026-11-17T08:31:00+00:00",
        },
        "tests": history,
    }


def html_for(**kwargs: Any) -> str:
    params: dict[str, Any] = {
        "vehicle": saved_vehicle(),
        "mot": saved_mot(),
        "format": "full",
        "source": "saved",
        "generated_at": GENERATED,
    }
    params.update(kwargs)
    return render_vehicle_report_html(build_report_context(**params))


def png_bytes(size: tuple[int, int] = (64, 48), fmt: str = "PNG") -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, (90, 120, 160)).save(buffer, format=fmt)
    return buffer.getvalue()


# --------------------------------------------------------------------------- formatting


def test_numbers_and_dates_follow_the_approved_formats() -> None:
    html = html_for(vehicle=saved_vehicle(engine_size="1995", fuel_type="PETROL"))
    assert ">2021<" in html and "2,021" not in html  # a year never gets a separator
    assert "1995 cc" in html  # engine capacity as in the approved mockup
    assert "30,599 mi" in html
    assert "Mar 2021" in html  # month-precision first registration
    assert "1 Mar 2027" in html and "Generated 17 Nov 2026" in html
    assert "£200" in html and "£17.50 / month" in html and "£105.00 / 6 months" in html
    assert "CO<sub>2</sub> emissions" in html
    assert "2026–27 standard rate" in html


def test_report_never_includes_identifiers_vin_or_owner() -> None:
    html = html_for()
    for secret in (VIN, OWNER_ID, HOME_ID, "6a4c1f0e-0000-4000-8000-000000000001"):
        assert secret not in html


def test_provider_text_is_escaped() -> None:
    mot = saved_mot()
    mot["tests"][0]["defects"] = [
        {"category": "advisory", "text": '<img src="file:///etc/passwd">', "dangerous": False}
    ]
    html = html_for(mot=mot)
    assert '<img src="file:///etc/passwd">' not in html
    assert "&lt;img src=&#34;file:///etc/passwd&#34;&gt;" in html


def test_stacked_combining_marks_are_capped_without_losing_text() -> None:
    """HarfBuzz CVE-2023-25193 control: the quadratic trigger is removed."""
    mot = saved_mot()
    mot["tests"][0]["defects"] = [
        {"category": "advisory", "text": "Tyre:" + "\u0301" * 20000 + " worn", "dangerous": False}
    ]
    context = build_report_context(
        vehicle=saved_vehicle(), mot=mot, format="full", source="saved", generated_at=GENERATED
    )
    assert context["mot"]["tests"][0]["defects"][0]["text"] == "Tyre:" + "\u0301" * 4 + " worn"


def test_long_legitimate_text_is_kept_in_full() -> None:
    advisory = ("Nearside front brake disc worn, pitted or scored. " * 60)[:2900]
    mot = saved_mot()
    mot["tests"][0]["defects"] = [{"category": "advisory", "text": advisory, "dangerous": False}]
    context = build_report_context(
        vehicle=saved_vehicle(colour="Metallic " * 25),
        mot=mot,
        format="full",
        source="saved",
        generated_at=GENERATED,
    )
    assert context["mot"]["tests"][0]["defects"][0]["text"] == advisory  # 2,900 chars, intact
    assert "shortened" not in render_vehicle_report_html(context)


def test_oversized_text_is_shortened_visibly_never_silently() -> None:
    mot = saved_mot()
    mot["tests"][0]["defects"] = [{"category": "advisory", "text": "x" * 9000, "dangerous": False}]
    context = build_report_context(
        vehicle=saved_vehicle(make="M" * 1000, model=None),
        mot=mot,
        format="full",
        source="lookup",
        generated_at=GENERATED,
    )
    text = context["mot"]["tests"][0]["defects"][0]["text"]
    assert text.startswith("x" * 4000) and text.endswith("… [shortened from 9,000 characters]")
    assert context["name"].endswith("… [shortened from 1,000 characters]")


def test_report_budget_keeps_every_test_and_says_what_is_omitted() -> None:
    long_defect = {"category": "advisory", "text": "y" * 3990, "dangerous": False}
    mot = saved_mot(tests=60)
    for test in mot["tests"]:
        test["defects"] = [long_defect] * 1
    context = build_report_context(
        vehicle=saved_vehicle(), mot=mot, format="full", source="saved", generated_at=GENERATED
    )
    tests = context["mot"]["tests"]
    assert len(tests) == 60  # the complete history is still listed
    assert context["mot"]["tests_with_omitted_detail"] > 0
    assert context["mot"]["defect_count"] == 60  # counts include omitted detail
    shown = sum(len(d["text"]) for t in tests for d in t["defects"])
    assert shown <= 150_000
    html = render_vehicle_report_html(context)
    assert "shown because this report reached its length limit" in html


def test_wording_is_vehicle_report_only() -> None:
    for fmt in ("full", "essential"):
        html = html_for(format=fmt).lower()
        assert "vehicle report" in html
        for banned in ("sale report", "buyer", "for sale"):
            assert banned not in html


# --------------------------------------------------------------------------- household details


def test_saved_report_labels_the_nickname_as_household_entered() -> None:
    html = html_for(photo_uri="data:image/jpeg;base64,AAAA")
    assert "<small>Nickname</small>Pebble" in html
    note = "The nickname and photo were added by your household, not provided by DVLA or DVSA."
    assert note in html
    assert "data:image/jpeg;base64,AAAA" in html


def test_household_details_can_be_excluded_for_sharing() -> None:
    html = html_for(photo_uri="data:image/jpeg;base64,AAAA", include_household_details=False)
    assert "Pebble" not in html
    assert "data:image/jpeg;base64,AAAA" not in html
    assert "added by your household" not in html


def test_excluding_household_details_never_falls_back_to_the_nickname_title() -> None:
    sparse = {"nickname": "Grandad's van", "registration": "ZZ99 ZZZ"}
    assert "Grandad" in html_for(vehicle=sparse, mot=None)
    html = html_for(vehicle=sparse, mot=None, include_household_details=False)
    assert "Grandad" not in html and "Your vehicle" in html


def test_lookup_reports_never_carry_household_details() -> None:
    html = html_for(source="lookup", photo_uri="data:image/jpeg;base64,AAAA")
    assert "Pebble" not in html and "data:image/jpeg;base64,AAAA" not in html
    assert "One-off lookup" in html


def test_lookup_mot_shape_is_supported() -> None:
    mot = {"status": "valid", "due_date": "2027-05-31", "tests": saved_mot()["tests"]}
    context = build_report_context(
        vehicle=saved_vehicle(checked_at="2026-11-17T09:05:00+00:00", last_successful_lookup=None),
        mot=mot,
        format="essential",
        source="lookup",
        generated_at=GENERATED,
    )
    assert context["mot"]["status"] == "MOT valid"
    assert context["mot"]["expiry"] == "31 May 2027"
    assert context["dvla_checked"] == "17 Nov 2026"


# --------------------------------------------------------------------------- missing data


def test_sparse_vehicle_renders_calm_empty_states() -> None:
    for fmt in ("full", "essential"):
        html = html_for(vehicle={"registration": "ZZ99 ZZZ"}, mot=None, format=fmt)
        assert "Unknown" not in html and "None" not in html
        assert "Tax details aren’t available for this vehicle yet." in html


def test_full_report_has_complete_history_and_essential_only_recent_tests() -> None:
    mot = saved_mot(tests=6)
    full = build_report_context(
        vehicle=saved_vehicle(), mot=mot, format="full", source="saved", generated_at=GENERATED
    )
    assert full["mot"]["count"] == 6 and len(full["mot"]["recent"]) == 3
    assert full["mot"]["tests"][1]["defects"][0]["label"] == "Dangerous"  # severity first
    essential_html = html_for(mot=mot, format="essential")
    assert "Complete MOT history" not in essential_html
    assert "Complete MOT history" in html_for(mot=mot, format="full")


# --------------------------------------------------------------------------- photos


def test_photo_is_revalidated_and_reencoded_as_bounded_jpeg() -> None:
    uri = prepare_report_photo(png_bytes((3000, 2000)))
    assert uri is not None and uri.startswith("data:image/jpeg;base64,")
    import base64

    with Image.open(io.BytesIO(base64.b64decode(uri.split(",", 1)[1]))) as image:
        assert max(image.size) <= 1200 and image.format == "JPEG"


@pytest.mark.parametrize("data", [b"", b"not an image", b"%!PS-Adobe-3.0 EPSF-3.0\n"])
def test_unusable_photo_falls_back_to_placeholder(data: bytes) -> None:
    assert prepare_report_photo(data) is None


def test_photo_formats_outside_the_allow_list_are_refused() -> None:
    assert prepare_report_photo(png_bytes(fmt="GIF")) is None


# --------------------------------------------------------------------------- PDF rendering


def _pages(**kwargs: Any) -> int:
    from weasyprint import HTML

    return len(HTML(string=html_for(**kwargs), url_fetcher=_url_fetcher()).render().pages)


def test_pdf_pagination_matches_the_approved_layout() -> None:
    assert _pages(format="essential") == 1
    assert _pages(format="essential", vehicle={"registration": "ZZ99 ZZZ"}, mot=None) == 1
    assert _pages(format="full") == 2
    long_history = saved_mot(tests=14)
    assert _pages(format="full", mot=long_history) <= 4


def test_every_brand_font_is_embedded_as_valid_distinct_data() -> None:
    import base64
    import re

    from mykhaya.vehicle_report_pdf import _assets_root, _static_assets

    css, logo = _static_assets(str(_assets_root(None)))
    assert "FONT:" not in css
    payloads = re.findall(r'url\("data:font/woff2;base64,([^"]+)"\)', css)
    assert len(payloads) == 4 and len(set(payloads)) == 4
    for payload in payloads:  # strict: no trailing junk from a placeholder collision
        assert base64.b64decode(payload, validate=True)[:4] == b"wOF2"
    assert logo.startswith("data:image/png;base64,")


def test_pdf_embeds_only_brand_fonts() -> None:
    from weasyprint import HTML

    document = HTML(string=html_for(), url_fetcher=_url_fetcher()).render()
    pdf = document.write_pdf(uncompressed_pdf=True)
    names = {
        line.split(b"/BaseFont /", 1)[1].split()[0].split(b"+", 1)[-1]
        for line in pdf.split(b"\n")
        if b"/BaseFont /" in line
    }
    assert names, "no fonts embedded"
    assert all(name.startswith((b"Figtree", b"Bricolage")) for name in names), names


def test_pdf_bytes_are_reproducible(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "0")
    kwargs: dict[str, Any] = {
        "vehicle": saved_vehicle(),
        "mot": saved_mot(),
        "format": "full",
        "generated_at": GENERATED,
        "photo": png_bytes(),
    }
    first = build_vehicle_report_pdf(**kwargs)
    assert first.startswith(b"%PDF-")
    assert build_vehicle_report_pdf(**kwargs) == first


@pytest.mark.parametrize(
    "url",
    ["file:///etc/passwd", "http://169.254.169.254/latest/meta-data/", "https://example.com/x.png"],
)
def test_renderer_refuses_every_non_data_resource(url: str) -> None:
    from weasyprint import HTML

    with pytest.raises(BaseException) as raised:  # noqa: B017 - WeasyPrint raises a BaseException
        HTML(string=f'<img src="{url}">', url_fetcher=_url_fetcher()).write_pdf()
    assert type(raised.value).__name__ == "FatalURLFetchingError"


def test_vehicle_report_filename_is_safe_and_predictable() -> None:
    assert (
        sanitise_report_filename(" ab/12 cde ", datetime(2026, 11, 18).date())
        == "MyKhaya-Vehicle-Report-AB-12-CDE-2026-11-18.pdf"
    )
