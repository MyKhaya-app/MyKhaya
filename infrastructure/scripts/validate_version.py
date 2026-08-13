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
class ValidationError(RuntimeError):
    pass


def workspace_package_patterns(workspace_file: Path = Path("pnpm-workspace.yaml")) -> list[str]:
    """The `packages:` glob patterns from pnpm-workspace.yaml — deliberately
    small, line-based parsing rather than a PyYAML dependency, since this
    script runs standalone (via plain `python3`, no requirements.txt) both in
    CI and locally, and the file's structure is a short, fixed list."""
    if not workspace_file.is_file():
        raise ValidationError(f"{workspace_file} does not exist")
    patterns: list[str] = []
    in_packages = False
    for line in workspace_file.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped == "packages:":
            in_packages = True
            continue
        if not in_packages:
            continue
        if stripped.startswith("- "):
            patterns.append(stripped.removeprefix("- ").strip())
        elif stripped and not stripped.startswith("#"):
            break
    if not patterns:
        raise ValidationError(f"{workspace_file} declares no packages: entries")
    return patterns


def workspace_package_manifests(workspace_file: Path = Path("pnpm-workspace.yaml")) -> list[Path]:
    """Every package.json that actually exists under a pattern
    pnpm-workspace.yaml declares — the single source of truth for which
    JS/TS components are real workspace members, so this validator can't
    drift from reality the way a hand-maintained path list did:
    apps/mobile/package.json was deliberately removed from the tree in
    commit 7ca7899 ("Commit to Dev") when the mobile app was pulled out of
    the workspace, but a static COMPONENT_MANIFESTS tuple here kept
    assuming it still existed, crashing every CI run unconditionally."""
    manifests: list[Path] = []
    for pattern in workspace_package_patterns(workspace_file):
        manifests.extend(sorted(Path().glob(f"{pattern}/package.json")))
    return manifests


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
    for path in workspace_package_manifests():
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
