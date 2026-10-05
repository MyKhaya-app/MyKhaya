"""Regression tests for the immutable production release deployment flow."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class ProductionDeploymentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        cls.script = (ROOT / "infrastructure/scripts/prod-deploy.sh").read_text(
            encoding="utf-8"
        )

    def test_makefile_requires_release_and_passes_tag(self) -> None:
        target = self.makefile[self.makefile.index("prod-update:") :]
        self.assertIn('test -n "$(RELEASE)"', target)
        self.assertIn('MYKHAYA_RELEASE_TAG="$(RELEASE)"', target)

    def test_requested_tag_is_fetched(self) -> None:
        self.assertIn(
            'git fetch origin main "refs/tags/$MYKHAYA_RELEASE_TAG:refs/tags/$MYKHAYA_RELEASE_TAG"',
            self.script,
        )

    def test_production_version_comes_from_release_tag(self) -> None:
        self.assertIn('MYKHAYA_VERSION="$MYKHAYA_RELEASE_TAG"', self.script)
        self.assertNotIn("cat VERSION", self.script)

    def test_production_channel_and_commit_metadata_are_exported_before_build(self) -> None:
        metadata = self.script.index('export MYKHAYA_VERSION MYKHAYA_COMMIT_SHA="$head_commit"')
        build = self.script.index("$COMPOSE build web api worker scheduler migrate")
        self.assertLess(metadata, build)
        self.assertIn("MYKHAYA_BUILD_CHANNEL=stable", self.script)
        self.assertIn("git rev-parse HEAD", self.script)

    def test_tag_commit_belongs_to_origin_main(self) -> None:
        self.assertIn('git merge-base --is-ancestor "$tag_commit" origin/main', self.script)

    def test_build_precedes_migration_and_application_replacement(self) -> None:
        build = self.script.index("$COMPOSE build web api worker scheduler migrate")
        migration = self.script.index("$COMPOSE run --rm --no-deps migrate", build)
        replacement = self.script.index(
            "$COMPOSE up -d --no-build caddy web api worker scheduler", migration
        )
        self.assertLess(build, migration)
        self.assertLess(migration, replacement)

    def test_backup_marker_is_retained(self) -> None:
        self.assertIn("MYKHAYA_BACKUP_MARKER", self.script)
        self.assertIn("verified backup marker is missing", self.script)

    def test_deployment_never_deletes_volumes_or_prunes(self) -> None:
        self.assertNotRegex(self.script, r"\bdown\s+-v\b|\bvolume\s+rm\b|\bprune\b")

    def test_application_services_start_with_no_build_after_images_build(self) -> None:
        build = self.script.index("$COMPOSE build web api worker scheduler migrate")
        start = self.script.index(
            "$COMPOSE up -d --no-build caddy web api worker scheduler"
        )
        self.assertLess(build, start)
        self.assertIn("--no-build", self.script[start : start + 100])


if __name__ == "__main__":
    unittest.main()
