import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class DevelopmentDeploymentTests(unittest.TestCase):
    def test_required_artifacts_are_present(self) -> None:
        for relative in (
            "compose.dev.yml",
            ".env.dev.example",
            "infrastructure/caddy/Caddyfile.dev",
            "infrastructure/scripts/dev-deploy.sh",
            "infrastructure/scripts/update-dev.sh",
            "docs/operations/dev-deployment.md",
        ):
            self.assertTrue((ROOT / relative).is_file(), relative)

    def test_update_never_deletes_volumes(self) -> None:
        script = (ROOT / "infrastructure/scripts/dev-deploy.sh").read_text(encoding="utf-8")
        wrapper = (ROOT / "infrastructure/scripts/update-dev.sh").read_text(encoding="utf-8")
        self.assertNotRegex(script, r"\bdown\s+-v\b|\bvolume\s+rm\b|\bprune\b")
        self.assertNotRegex(wrapper, r"\bdown\s+-v\b|\bvolume\s+rm\b|\bprune\b")
        self.assertIn("compose stop", script)

    def test_preflight_keeps_required_diagnostics(self) -> None:
        script = (ROOT / "infrastructure/scripts/dev-deploy.sh").read_text(encoding="utf-8")
        for diagnostic in (
            "missing .env",
            "missing required variables",
            "invalid JSON environment values",
            "is already occupied",
            "Docker is unavailable",
            "Docker Compose v2 is unavailable",
            "wrong Git branch",
            "uncommitted tracked deployment changes",
        ):
            self.assertIn(diagnostic, script)

    def test_build_and_migration_gate_container_replacement(self) -> None:
        script = (ROOT / "infrastructure/scripts/dev-deploy.sh").read_text(encoding="utf-8")
        build = script.index("compose build")
        migration = script.index("compose run --rm --no-deps migrate", build)
        app_start = script.index("compose up -d --no-build --no-deps api", migration)
        self.assertLess(build, migration)
        self.assertLess(migration, app_start)

    def test_dev_overlay_has_only_expected_published_services(self) -> None:
        overlay = (ROOT / "compose.dev.yml").read_text(encoding="utf-8")
        published_services = []
        current_service = None
        for line in overlay.splitlines():
            if line.startswith("  ") and not line.startswith("    ") and line.endswith(":"):
                current_service = line.strip().removesuffix(":")
            elif line == "    ports:" and current_service is not None:
                published_services.append(current_service)
        self.assertEqual(published_services, ["caddy", "mailpit"])
        self.assertIn('"127.0.0.1:${MYKHAYA_DEV_MAILPIT_PORT:-8025}:8025"', overlay)

    def test_makefile_exposes_supported_commands(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        for target in ("dev-up", "dev-down", "dev-logs", "dev-update"):
            self.assertRegex(makefile, rf"(?m)^{target}:")


if __name__ == "__main__":
    unittest.main()
