"""Guards against the colour palette silently drifting apart across its three
hand-maintained copies: mykhaya.colour_palette (source of truth for the API
and the database enum), packages/design-tokens/src/index.ts (frontend JS),
and packages/design-tokens/src/tokens.css (frontend CSS custom properties).

There is no code generation here on purpose — this test parses the actual TS
and CSS source files as text and compares them against the live Python
values, so any future edit to one file without the others fails a test
instead of shipping a mismatched palette.
"""

import re
from pathlib import Path

import pytest

from mykhaya.colour_palette import PALETTE_HEX, ColourToken


def _design_tokens_dir() -> Path:
    here = Path(__file__).resolve()
    # Different hop count depending on where this runs: inside the isolated
    # test Docker image (apps/api/Dockerfile's `test` stage copies just
    # `tests/` and `packages/design-tokens/` into /build) vs. a full local
    # checkout (apps/api/tests/../../../../packages/design-tokens).
    candidates = [
        here.parent.parent / "packages" / "design-tokens",
        here.parents[3] / "packages" / "design-tokens" if len(here.parents) > 3 else None,
    ]
    for candidate in candidates:
        if candidate and (candidate / "src" / "index.ts").exists():
            return candidate
    pytest.skip("packages/design-tokens not available in this environment")


def _parse_ts_palette(index_ts: str) -> tuple[list[str], dict[str, str]]:
    keys_block = re.search(r"PALETTE_KEYS\s*=\s*\[(.*?)\]", index_ts, re.DOTALL)
    assert keys_block, "PALETTE_KEYS array not found in design-tokens index.ts"
    keys = re.findall(r'"([a-z]+)"', keys_block.group(1))

    hex_block = re.search(r"PALETTE_HEX:[^{]*\{(.*?)\};", index_ts, re.DOTALL)
    assert hex_block, "PALETTE_HEX object not found in design-tokens index.ts"
    hex_map = dict(re.findall(r"(\w+):\s*\"(#[0-9A-Fa-f]{6})\"", hex_block.group(1)))
    return keys, hex_map


def _parse_css_palette(tokens_css: str) -> dict[str, str]:
    return dict(re.findall(r"--colour-palette-([a-z]+):\s*(#[0-9a-fA-F]{6});", tokens_css))


def test_palette_tokens_and_hex_values_match_across_python_ts_and_css() -> None:
    design_tokens_dir = _design_tokens_dir()
    index_ts = (design_tokens_dir / "src" / "index.ts").read_text(encoding="utf-8")
    tokens_css = (design_tokens_dir / "src" / "tokens.css").read_text(encoding="utf-8")

    python_keys = [token.value for token in ColourToken]
    python_hex = {token.value: hex_value.upper() for token, hex_value in PALETTE_HEX.items()}

    ts_keys, ts_hex_raw = _parse_ts_palette(index_ts)
    ts_hex = {key: value.upper() for key, value in ts_hex_raw.items()}

    css_hex_raw = _parse_css_palette(tokens_css)
    css_hex = {key: value.upper() for key, value in css_hex_raw.items()}

    # Every ColourToken must have exactly one PALETTE_HEX entry (a guard
    # against a token added to the enum but never given a colour).
    assert set(python_keys) == set(python_hex), (
        "mykhaya.colour_palette.ColourToken and PALETTE_HEX have diverged internally"
    )

    assert set(python_keys) == set(ts_keys), (
        f"Token names differ between mykhaya.colour_palette.ColourToken and "
        f"design-tokens PALETTE_KEYS: python-only={set(python_keys) - set(ts_keys)}, "
        f"ts-only={set(ts_keys) - set(python_keys)}"
    )
    assert set(python_keys) == set(ts_hex), (
        f"Token names differ between mykhaya.colour_palette and design-tokens "
        f"PALETTE_HEX: python-only={set(python_keys) - set(ts_hex)}, "
        f"ts-only={set(ts_hex) - set(python_keys)}"
    )
    assert set(python_keys) == set(css_hex), (
        f"Token names differ between mykhaya.colour_palette and tokens.css "
        f"--colour-palette-* variables: python-only={set(python_keys) - set(css_hex)}, "
        f"css-only={set(css_hex) - set(python_keys)}"
    )

    mismatched_ts = {
        key: (python_hex[key], ts_hex[key]) for key in python_hex if python_hex[key] != ts_hex[key]
    }
    assert not mismatched_ts, (
        f"Hex values differ between Python and design-tokens TS: {mismatched_ts}"
    )

    mismatched_css = {
        key: (python_hex[key], css_hex[key])
        for key in python_hex
        if python_hex[key] != css_hex[key]
    }
    assert not mismatched_css, f"Hex values differ between Python and tokens.css: {mismatched_css}"

    # 16-18 well-chosen colours, per the design requirement — not a hard cap
    # going forward, but a sanity check that nobody accidentally collapsed
    # or exploded the curated set.
    assert 16 <= len(python_keys) <= 18
