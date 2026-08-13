"""Regression tests for infrastructure/scripts/validate_version.py.

Covers the exact bug found when the `quality` CI workflow's "Validate VERSION"
step started failing immediately: apps/mobile/package.json was deliberately
removed from the tree (commit 7ca7899, "Commit to Dev" — the mobile app was
pulled out of the pnpm workspace) but a hand-maintained COMPONENT_MANIFESTS
tuple in this script still assumed it existed, crashing with an unhandled
FileNotFoundError before any real validation ran. The fix derives the
component list from pnpm-workspace.yaml itself instead of a parallel,
driftable list — these tests prove that derivation is correct and that the
real repository actually validates cleanly with it.
"""

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

_spec = importlib.util.spec_from_file_location(
    "validate_version", ROOT / "infrastructure/scripts/validate_version.py"
)
assert _spec is not None and _spec.loader is not None
validate_version = importlib.util.module_from_spec(_spec)
sys.modules["validate_version"] = validate_version
_spec.loader.exec_module(validate_version)


class WorkspacePackagePatternsTests(unittest.TestCase):
    def test_parses_literal_and_glob_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace_file = Path(tmp) / "pnpm-workspace.yaml"
            workspace_file.write_text("packages:\n  - apps/web\n  - packages/*\n", encoding="utf-8")
            patterns = validate_version.workspace_package_patterns(workspace_file)
        self.assertEqual(patterns, ["apps/web", "packages/*"])

    def test_missing_file_raises_validation_error_not_a_crash(self) -> None:
        missing = Path(tempfile.gettempdir()) / "definitely-does-not-exist-pnpm-workspace.yaml"
        with self.assertRaises(validate_version.ValidationError):
            validate_version.workspace_package_patterns(missing)

    def test_no_packages_entries_raises_validation_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace_file = Path(tmp) / "pnpm-workspace.yaml"
            workspace_file.write_text("other: []\n", encoding="utf-8")
            with self.assertRaises(validate_version.ValidationError):
                validate_version.workspace_package_patterns(workspace_file)


class WorkspacePackageManifestsTests(unittest.TestCase):
    def test_only_resolves_manifests_that_actually_exist_under_declared_patterns(self) -> None:
        """The exact regression: a workspace member that was removed from
        disk (like apps/mobile) must simply be absent from the result, not
        raise, and a directory NOT declared in pnpm-workspace.yaml (even if
        it happens to contain a package.json) must never be picked up."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "apps/web").mkdir(parents=True)
            (root / "apps/web/package.json").write_text('{"version": "1.2.3"}', encoding="utf-8")
            (root / "apps/mobile").mkdir(parents=True)  # exists, but no package.json — like today
            (root / "packages/design-tokens").mkdir(parents=True)
            (root / "packages/design-tokens/package.json").write_text(
                '{"version": "1.2.3"}', encoding="utf-8"
            )
            (root / "not-a-workspace-package").mkdir(parents=True)
            (root / "not-a-workspace-package/package.json").write_text(
                '{"version": "9.9.9"}', encoding="utf-8"
            )
            workspace_file = root / "pnpm-workspace.yaml"
            workspace_file.write_text("packages:\n  - apps/web\n  - packages/*\n", encoding="utf-8")

            previous_cwd = Path.cwd()
            os.chdir(root)
            try:
                manifests = validate_version.workspace_package_manifests(workspace_file)
            finally:
                os.chdir(previous_cwd)

        manifest_paths = {path.as_posix() for path in manifests}
        self.assertEqual(
            manifest_paths, {"apps/web/package.json", "packages/design-tokens/package.json"}
        )
        self.assertNotIn("apps/mobile/package.json", manifest_paths)
        self.assertNotIn("not-a-workspace-package/package.json", manifest_paths)


class RealRepositoryValidationTests(unittest.TestCase):
    """Runs the actual validator against the real repository state — the
    thing CI actually does — not just a synthetic fixture."""

    def setUp(self) -> None:
        self._previous_cwd = Path.cwd()
        os.chdir(ROOT)

    def tearDown(self) -> None:
        os.chdir(self._previous_cwd)

    def test_apps_mobile_is_not_a_current_workspace_member(self) -> None:
        self.assertFalse(
            (ROOT / "apps/mobile/package.json").exists(),
            "If this now exists, apps/mobile has been reintroduced as a real "
            "workspace package — update pnpm-workspace.yaml (component "
            "discovery here follows it automatically) rather than assuming "
            "this test is stale.",
        )

    def test_component_versions_excludes_mobile_and_matches_version_file(self) -> None:
        versions = validate_version.component_versions()
        self.assertNotIn("apps/mobile/package.json", versions)
        self.assertIn("apps/web/package.json", versions)
        self.assertIn("apps/api/pyproject.toml", versions)
        expected = validate_version.root_version()
        for path, value in versions.items():
            self.assertEqual(value, expected, f"{path} does not match VERSION={expected}")

    def test_main_passes_against_the_real_repository(self) -> None:
        self.assertEqual(validate_version.main(), 0)


if __name__ == "__main__":
    unittest.main()
