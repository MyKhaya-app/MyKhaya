#!/usr/bin/env python3
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

STABLE_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
DEV_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)-dev(?:\+[0-9A-Za-z.-]+)?$")
TAG_RE = re.compile(r"^v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


class ValidationError(RuntimeError):
    pass


def run_git(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if completed.returncode != 0:
        raise ValidationError(f"git {' '.join(args)} failed: {completed.stderr.strip()}")
    return completed.stdout.strip()


def parse_stable(version: str) -> tuple[int, int, int]:
    match = STABLE_RE.fullmatch(version)
    if not match:
        raise ValidationError(f"Stable version is invalid: {version}")
    return tuple(int(group) for group in match.groups())


def release_tuple(version: str) -> tuple[int, int, int]:
    stable_match = STABLE_RE.fullmatch(version)
    if stable_match:
        return tuple(int(group) for group in stable_match.groups())
    dev_match = DEV_RE.fullmatch(version)
    if dev_match:
        return tuple(int(group) for group in dev_match.groups())
    raise ValidationError(
        "VERSION must match MAJOR.MINOR.PATCH or MAJOR.MINOR.PATCH-dev[+metadata]"
    )


def latest_stable_tag() -> tuple[str, tuple[int, int, int]] | None:
    tags = run_git("tag", "--list", "v*").splitlines()
    parsed: list[tuple[str, tuple[int, int, int]]] = []
    for tag in tags:
        tag = tag.strip()
        match = TAG_RE.fullmatch(tag)
        if not match:
            continue
        parsed.append((tag, tuple(int(group) for group in match.groups())))
    if not parsed:
        return None
    parsed.sort(key=lambda item: item[1])
    return parsed[-1]


def tag_points_to_main(sha: str) -> bool:
    for candidate in ("origin/main", "main"):
        completed = subprocess.run(
            ["git", "merge-base", "--is-ancestor", sha, candidate], check=False
        )
        if completed.returncode == 0:
            return True
    return False


def assert_version_file() -> str:
    version_file = Path("VERSION")
    if not version_file.exists():
        raise ValidationError("Missing VERSION file")
    version = version_file.read_text(encoding="utf-8").strip()
    if not version:
        raise ValidationError("VERSION file is empty")
    _ = release_tuple(version)
    return version


def assert_branch_rules(version: str, ref: str) -> None:
    if ref == "refs/heads/main" and not STABLE_RE.fullmatch(version):
        raise ValidationError("main must use a stable MAJOR.MINOR.PATCH version without -dev")
    if ref == "refs/heads/dev" and not DEV_RE.fullmatch(version):
        raise ValidationError("dev must use a development version ending in -dev")


def assert_tag_rules(version: str, ref_name: str, sha: str) -> None:
    match = TAG_RE.fullmatch(ref_name)
    if not match:
        raise ValidationError("Stable tags must use vMAJOR.MINOR.PATCH")
    tagged_version = ".".join(match.groups())
    if version != tagged_version:
        raise ValidationError(
            f"Tag {ref_name} does not match VERSION {version}; expected {tagged_version}"
        )
    if not tag_points_to_main(sha):
        raise ValidationError(f"Tag {ref_name} is not reachable from main")


def assert_not_regressing(version: str, ref: str, ref_name: str) -> None:
    latest = latest_stable_tag()
    if not latest:
        return
    latest_tag, latest_tuple = latest
    current_tuple = release_tuple(version)
    if current_tuple < latest_tuple:
        raise ValidationError(
            f"VERSION {version} is lower than latest stable tag {latest_tag}"
        )
    if STABLE_RE.fullmatch(version):
        existing_tags = {
            line.strip() for line in run_git("tag", "--list", f"v{version}").splitlines() if line.strip()
        }
        current_tag = ref_name if ref.startswith("refs/tags/") else ""
        if existing_tags and current_tag not in existing_tags:
            raise ValidationError(f"Stable version {version} already exists as a tag")


def assert_component_alignment(version: str) -> None:
    mobile_config = Path("apps/mobile/app.config.ts")
    if not mobile_config.exists():
        raise ValidationError("Missing apps/mobile/app.config.ts")
    if '"..", "..", "VERSION"' not in mobile_config.read_text(encoding="utf-8"):
        raise ValidationError("Mobile config must read the root VERSION file")

    web_component = Path("apps/web/components/app-version.tsx")
    if not web_component.exists():
        raise ValidationError("Missing apps/web/components/app-version.tsx")
    if "/api/v1/health/build" not in web_component.read_text(encoding="utf-8"):
        raise ValidationError("Web app version display must resolve through the API build endpoint")

    api_config = Path("apps/api/mykhaya/config.py").read_text(encoding="utf-8")
    if "version: str = _read_repo_version()" not in api_config:
        raise ValidationError("API settings.version must resolve from VERSION")

    if not release_tuple(version):
        raise ValidationError("Version parsing failed")


def main() -> int:
    version = assert_version_file()
    ref = os.getenv("GITHUB_REF", "")
    ref_name = os.getenv("GITHUB_REF_NAME", "")
    sha = os.getenv("GITHUB_SHA", run_git("rev-parse", "HEAD"))

    assert_branch_rules(version, ref)
    if ref.startswith("refs/tags/"):
        assert_tag_rules(version, ref_name, sha)
    assert_not_regressing(version, ref, ref_name)
    assert_component_alignment(version)

    print(f"Version validation passed for VERSION={version} ref={ref or 'local'}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValidationError as exc:
        print(f"Version validation failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
