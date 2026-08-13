"""Settings.version / resolve_app_version() — the single source of truth for
FastAPI(version=...). Regression coverage for a CI failure where CI's fresh
`cp .env.example .env` carried over MYKHAYA_VERSION= (blank, documented as
"leave blank to use the repository VERSION file"), which pydantic-settings
still treats as an explicit value, reaching FastAPI(version="") and tripping
FastAPI's own long-standing `assert self.version` at app construction. This
was never a FastAPI regression (the assertion already exists at the
pyproject.toml floor of fastapi==0.116.0) — it was MyKhaya not distinguishing
"blank" from "explicitly overridden".
"""

import importlib.metadata

import pytest
from fastapi import FastAPI

from mykhaya.config import Settings, resolve_app_version

SECRET_KEY = "a" * 40


def _base_kwargs(**overrides: object) -> dict[str, object]:
    kwargs: dict[str, object] = {
        "secret_key": SECRET_KEY,
        "environment": "test",
    }
    kwargs.update(overrides)
    return kwargs


def test_resolve_app_version_returns_non_empty_from_source_tree() -> None:
    """No env override present: running from source must resolve a real,
    non-empty version (repository VERSION file or installed package
    metadata — both are kept in sync by validate_version.py)."""
    version = resolve_app_version()
    assert version
    assert version != "unknown"


def test_settings_default_version_is_never_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MYKHAYA_VERSION", raising=False)
    settings = Settings.model_validate(_base_kwargs())
    assert settings.version


def test_blank_version_override_falls_back_instead_of_reaching_fastapi_empty() -> None:
    """Exact regression case: MYKHAYA_VERSION= (present, blank) must not
    reach Settings.version as an empty string."""
    settings = Settings.model_validate(_base_kwargs(version=""))
    assert settings.version != ""
    assert settings.version

    # The actual failure mode seen in CI: FastAPI(version="") raises
    # AssertionError. Constructing it here proves the fix, not just that
    # Settings.version is truthy in isolation.
    app = FastAPI(title="MyKhaya API", version=settings.version)
    assert app.version == settings.version


def test_explicit_version_override_takes_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MYKHAYA_VERSION", "9.9.9-test")
    assert resolve_app_version() == "9.9.9-test"


def test_placeholder_unknown_override_does_not_block_a_better_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """compose.yml's `${MYKHAYA_VERSION:-unknown}` substitution and the
    Dockerfiles' `ARG MYKHAYA_VERSION=unknown` mean a literal "unknown" is a
    routine, non-meaningful value — it must not shadow a real version that's
    actually available from package metadata or the repository VERSION
    file."""
    monkeypatch.setenv("MYKHAYA_VERSION", "unknown")
    assert resolve_app_version() != "unknown"


def test_missing_package_metadata_falls_back_to_repo_version_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MYKHAYA_VERSION", raising=False)

    def _raise_not_found(_name: str) -> str:
        raise importlib.metadata.PackageNotFoundError

    monkeypatch.setattr(importlib.metadata, "version", _raise_not_found)
    version = resolve_app_version()
    assert version
    assert version != "unknown"


def test_app_module_constructs_fastapi_with_non_empty_version() -> None:
    """The actual application object, imported the same way the ASGI server
    and pytest collection do — proves main.py wires settings.version into
    FastAPI(version=...) without ever producing an empty value."""
    from mykhaya.main import app

    assert app.version
