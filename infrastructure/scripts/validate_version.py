#!/usr/bin/env python3
"""Validate the single, branch-independent MyKhaya version."""

from __future__ import annotations

import json
import os
import re
import sys
import tomllib
from pathlib import Path

SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
COMPONENT_MANIFESTS = (
    Path("apps/web/package.json"),
    Path("apps/mobile/package.json"),
    Path("packages/api-client/package.json"),
    Path("packages/design-tokens/package.json"),
    Path("packages/eslint-config/package.json"),
    Path("packages/shared-types/package.json"),
    Path("packages/typescript-config/package.json"),
)


class ValidationError(RuntimeError):
    pass


def root_version() -> str:
    path = Path("VERSION")
    if not path.is_file():
        raise ValidationError("VERSION does not exist")
    value = path.read_text(encoding="utf-8").strip()
    if not SEMVER_RE.fullmatch(value):
        raise ValidationError(f"VERSION is not valid semantic versioning: {value!r}")
    return value


def component_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    api_data = tomllib.loads(Path("apps/api/pyproject.toml").read_text(encoding="utf-8"))
    versions["apps/api/pyproject.toml"] = str(api_data["project"]["version"])
    for path in COMPONENT_MANIFESTS:
        data = json.loads(path.read_text(encoding="utf-8"))
        versions[path.as_posix()] = str(data["version"])
    return versions


def validate_tag(version: str) -> None:
    ref = os.getenv("GITHUB_REF", "")
    if not ref.startswith("refs/tags/"):
        return
    tag = ref.removeprefix("refs/tags/")
    if tag != f"v{version}":
        raise ValidationError(f"release tag {tag!r} does not match VERSION {version!r}")


def main() -> int:
    version = root_version()
    mismatches = {
        path: value for path, value in component_versions().items() if value != version
    }
    if mismatches:
        details = ", ".join(f"{path}={value}" for path, value in mismatches.items())
        raise ValidationError(f"component versions do not match VERSION {version}: {details}")
    validate_tag(version)
    print(f"Version validation passed for VERSION={version}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValidationError as exc:
        print(f"Version validation failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
