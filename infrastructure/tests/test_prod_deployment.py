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
        cls.compose = (ROOT / "compose.production.yml").read_text(encoding="utf-8")
        cls.base_compose = (ROOT / "compose.yml").read_text(encoding="utf-8")
        cls.caddy = (ROOT / "infrastructure/caddy/Caddyfile.production").read_text(
            encoding="utf-8"
        )
        cls.health = (ROOT / "infrastructure/scripts/prod-health.sh").read_text(
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

    def test_production_preflight_requires_installation_values(self) -> None:
        self.assertIn("require_installation_config", self.script)
        for key in (
            "MYKHAYA_REGISTRATION_MODE",
            "MYKHAYA_PUBLIC_WEB_URL",
            "MYKHAYA_ADMIN_URL",
            "MYKHAYA_STATUS_URL",
            "MYKHAYA_NATIVE_API_URL",
            "MYKHAYA_CORS_ORIGINS",
            "MYKHAYA_TRUSTED_HOSTS",
            "MYKHAYA_TRUSTED_PROXY_CIDRS",
            "WEB_DOMAIN",
            "API_DOMAIN",
            "ADMIN_DOMAIN",
            "STATUS_DOMAIN",
            "MYKHAYA_CADDY_TRUSTED_PROXY_CIDRS",
        ):
            self.assertIn(key, self.script)
        self.assertLess(
            self.script.index("require_installation_config"),
            self.script.index("$COMPOSE config --quiet"),
        )

    def test_install_validates_before_starting_or_migrating(self) -> None:
        install = (ROOT / "infrastructure/scripts/prod-install.sh").read_text(encoding="utf-8")
        self.assertLess(install.index("prod-deploy.sh validate"), install.index("up -d postgres redis"))
        self.assertLess(install.index("prod-deploy.sh validate"), install.index("run --rm --no-deps migrate"))

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

    def test_production_trusted_hosts_include_loopback_and_all_origins(self) -> None:
        self.assertNotIn("MYKHAYA_TRUSTED_HOSTS", self.compose)
        self.assertNotIn("MYKHAYA_CORS_ORIGINS", self.compose)
        self.assertNotIn("MYKHAYA_PUBLIC_WEB_URL", self.compose)

    def test_production_application_policy_is_not_hardcoded_in_compose(self) -> None:
        for key in (
            "MYKHAYA_REGISTRATION_MODE",
            "MYKHAYA_DEFAULT_TIMEZONE",
            "MYKHAYA_DEFAULT_LOCALE",
            "MYKHAYA_WEEK_START",
        ):
            self.assertNotIn(key, self.compose)
        self.assertIn("MYKHAYA_ENVIRONMENT: production", self.compose)
        self.assertIn("MYKHAYA_BUILD_CHANNEL: stable", self.compose)

    def test_production_domains_are_required_compose_substitutions(self) -> None:
        for key in ("WEB_DOMAIN", "API_DOMAIN", "ADMIN_DOMAIN", "STATUS_DOMAIN"):
            self.assertIn(f'{key}: "${{{key}:?Set {key} in the production .env}}"', self.compose)

    def test_production_template_owns_installation_policy_and_api_origin(self) -> None:
        template = (ROOT / ".env.production.example").read_text(encoding="utf-8")
        self.assertIn("MYKHAYA_REGISTRATION_MODE=open", template)
        self.assertIn("MYKHAYA_NATIVE_API_URL=https://api.mykhaya.app", template)
        self.assertIn("API_DOMAIN=api.mykhaya.app", template)

    def test_production_caddy_uses_http_origins_and_https_upstream_scheme(self) -> None:
        for address in (
            "http://{$WEB_DOMAIN:mykhaya.app} {",
            "http://{$API_DOMAIN:api.mykhaya.app} {",
            "http://{$ADMIN_DOMAIN:admin.mykhaya.app} {",
            "http://{$STATUS_DOMAIN:status.mykhaya.app} {",
        ):
            self.assertIn(address, self.caddy)
        self.assertNotRegex(self.caddy, r"(?m)^\{\$[^}]+\} \{")
        self.assertIn("header_up X-Forwarded-Proto https", self.caddy)

    def test_production_publishes_only_the_http_origin_port(self) -> None:
        self.assertIn('ports: ["80:80"]', self.compose)
        self.assertNotIn("443:443", self.compose)
        self.assertNotIn("443:443/udp", self.compose)

    def test_production_home_migration_storage_isolated_from_dev(self) -> None:
        base = (ROOT / "compose.yml").read_text(encoding="utf-8")
        self.assertIn("home_migration_data:/data/home-migrations", base)
        self.assertIn("name: mykhaya_prod_home_migration_data", self.compose)

    def test_production_health_checks_use_http_loopback_and_web_host(self) -> None:
        self.assertIn(
            "WEB_DOMAIN=${WEB_DOMAIN:-$(sed -n 's/^WEB_DOMAIN=//p' .env 2>/dev/null | tail -n 1 | tr -d '\\r')}",
            self.health,
        )
        self.assertIn("WEB_DOMAIN=${WEB_DOMAIN:-mykhaya.app}", self.health)
        for endpoint in ("live", "ready", "build"):
            self.assertIn(f"http://127.0.0.1/api/v1/health/{endpoint}", self.health)
        self.assertIn('-H "Host: $WEB_DOMAIN"', self.health)
        self.assertIn("build_status=$(curl -sS", self.health)
        self.assertIn("-w '%{http_code}'", self.health)
        self.assertIn('[ "$build_status" = 401 ]', self.health)
        self.assertNotIn("curl -fsS --max-time 10 -H \"Host: $WEB_DOMAIN\" http://127.0.0.1/api/v1/health/build", self.health)
        self.assertNotIn("https://mykhaya.app", self.health)
        self.assertNotIn("--resolve", self.health)

    def test_release_metadata_is_wired_to_every_application_runtime(self) -> None:
        for service in ("api", "worker", "scheduler"):
            self.assertIn("MYKHAYA_VERSION: \"${MYKHAYA_VERSION:-dev}\"", self.base_compose)
            self.assertIn("MYKHAYA_COMMIT_SHA: \"${MYKHAYA_COMMIT_SHA:-unknown}\"", self.base_compose)
            self.assertIn("MYKHAYA_BUILD_TIME: \"${MYKHAYA_BUILD_TIME:-unknown}\"", self.base_compose)
            self.assertIn("MYKHAYA_BUILD_CHANNEL: \"${MYKHAYA_BUILD_CHANNEL:-development}\"", self.base_compose)
            self.assertIn(service, self.base_compose)
        web_start = self.base_compose.index("\n  web:\n    build:")
        api_start = self.base_compose.index("\n  api: &api\n", web_start)
        web_block = self.base_compose[web_start:api_start]
        for key, default in (("MYKHAYA_VERSION", "dev"), ("MYKHAYA_COMMIT_SHA", "unknown"), ("MYKHAYA_BUILD_TIME", "unknown"), ("MYKHAYA_BUILD_CHANNEL", "development")):
            self.assertIn(f'{key}: "${{{key}:-{default}}}"', web_block)

    def test_release_metadata_is_exported_before_follow_up_compose_operations(self) -> None:
        export = 'export MYKHAYA_VERSION MYKHAYA_COMMIT_SHA="$head_commit"'
        for operation in (
            "$COMPOSE build web api worker scheduler migrate",
            "$COMPOSE run --rm --no-deps migrate",
            "$COMPOSE up -d --no-build caddy web api worker scheduler",
        ):
            self.assertLess(self.script.index(export), self.script.index(operation))


if __name__ == "__main__":
    unittest.main()
