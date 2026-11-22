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
            "infrastructure/scripts/check_dev_networks.py",
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

    def test_network_drift_is_checked_before_build_or_container_replacement(self) -> None:
        script = (ROOT / "infrastructure/scripts/dev-deploy.sh").read_text(encoding="utf-8")
        marker = "check_network_drift\n  report_new_env_variables"
        deploy_start = script.index("deploy()")
        self.assertLess(script.index(marker), script.index("compose build"))
        self.assertLess(
            script.index(marker),
            script.index("compose up -d --no-build --no-deps api", deploy_start),
        )

    def test_explicit_network_migration_preserves_data_services(self) -> None:
        script = (ROOT / "infrastructure/scripts/dev-deploy.sh").read_text(encoding="utf-8")
        migration = script[script.index("migrate_networks()") : script.index("deploy()")]
        self.assertIn("compose stop caddy web api worker scheduler", migration)
        self.assertIn("docker network rm mykhaya_edge mykhaya_app", migration)
        self.assertNotIn("postgres", migration)
        self.assertNotIn("redis", migration)
        self.assertNotIn("down -v", migration)

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

    def test_dev_health_checks_follow_the_dev_compose_default_port(self) -> None:
        script = (ROOT / "infrastructure/scripts/dev-deploy.sh").read_text(encoding="utf-8")
        example = (ROOT / ".env.dev.example").read_text(encoding="utf-8")
        self.assertEqual(script.count("host_port=${host_port:-8089}"), 2)
        self.assertIn("MYKHAYA_DEV_HOST_PORT=8089", example)

    def test_build_and_migration_gate_container_replacement(self) -> None:
        script = (ROOT / "infrastructure/scripts/dev-deploy.sh").read_text(encoding="utf-8")
        build = script.index("compose build")
        migration = script.index("compose run --rm --no-deps migrate", build)
        app_start = script.index("compose up -d --no-build --no-deps api", migration)
        self.assertLess(build, migration)
        self.assertLess(migration, app_start)

    def test_dev_build_metadata_is_explicit(self) -> None:
        script = (ROOT / "infrastructure/scripts/dev-deploy.sh").read_text(encoding="utf-8")
        metadata = script[script.index("set_build_metadata()") : script.index("wait_healthy()")]
        self.assertIn("MYKHAYA_VERSION=dev", metadata)
        self.assertIn("MYKHAYA_BUILD_CHANNEL=development", metadata)
        self.assertIn("git rev-parse HEAD", metadata)

    def test_caddy_is_recreated_after_configuration_changes(self) -> None:
        script = (ROOT / "infrastructure/scripts/dev-deploy.sh").read_text(encoding="utf-8")
        self.assertIn(
            "compose up -d --force-recreate --no-build --no-deps caddy mailpit",
            script,
        )

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

    def test_api_runtime_leaves_proxy_resolution_to_mykhaya(self) -> None:
        dockerfile = (ROOT / "apps/api/Dockerfile").read_text(encoding="utf-8")
        self.assertIn(
            'CMD ["uvicorn","mykhaya.main:app","--host","0.0.0.0","--port","8000"]',
            dockerfile,
        )
        self.assertNotIn("--proxy-headers", dockerfile)
        self.assertNotIn("--forwarded-allow-ips", dockerfile)

    def test_home_migration_storage_isolated_and_writable_for_api(self) -> None:
        compose = (ROOT / "compose.yml").read_text(encoding="utf-8")
        dev = (ROOT / "compose.dev.yml").read_text(encoding="utf-8")
        dockerfile = (ROOT / "apps/api/Dockerfile").read_text(encoding="utf-8")
        self.assertIn("home_migration_data:/data/home-migrations", compose)
        self.assertIn("home_migration_data: {}", compose)
        self.assertIn("name: mykhaya_dev_home_migration_data", dev)
        self.assertIn("/data/home-migrations", dockerfile)
        self.assertIn("chown mykhaya:mykhaya", dockerfile)

    def script(self) -> str:
        return (ROOT / "infrastructure/scripts/dev-deploy.sh").read_text(encoding="utf-8")

    def test_legacy_mode_is_the_unchanged_default(self) -> None:
        script = self.script()
        self.assertIn('DEV_CONFIG_ROOT=${MYKHAYA_DEV_CONFIG_ROOT:-}', script)
        self.assertIn('    docker compose -f compose.yml -f compose.dev.yml "$@"', script)
        self.assertIn('[ -f .env ] || die "missing .env; run: cp .env.dev.example .env"', script)

    def test_service_env_mode_never_reads_the_root_dotenv(self) -> None:
        script = self.script()
        compose_fn = script[script.index("compose() {") : script.index("say() {")]
        service_branch = compose_fn[: compose_fn.index("  else")]
        self.assertIn('--env-file "$DEV_CONFIG_ROOT/compose.env"', service_branch)
        self.assertIn("-f compose.dev.service-env.yml", service_branch)
        for name in ("MYKHAYA_DB_PASSWORD=", "MYKHAYA_MIGRATION_DB_PASSWORD=",
                     "MYKHAYA_POSTGRES_ADMIN_PASSWORD="):
            self.assertIn(name, service_branch)
        self.assertIn('ENV_SOURCE="$DEV_CONFIG_ROOT/compose.env"', script)

    def test_service_env_validation_precedes_any_build_or_restart(self) -> None:
        script = self.script()
        preflight = script[script.index("preflight() {") : script.index("set_build_metadata()")]
        self.assertIn("validate_env", preflight)
        self.assertIn("check_resolved_service_env", preflight)
        self.assertIn("check_compose_overrides_supported", preflight)
        deploy = script[script.index("deploy() {") :]
        self.assertLess(deploy.index("preflight"), deploy.index("compose build"))
        self.assertIn("service_env_contract.py", script)
        self.assertIn('--config-root "$DEV_CONFIG_ROOT"', script)
        self.assertNotIn("--no-interpolate", script)  # unparseable on older Compose
        self.assertIn("nothing was built, stopped or restarted", script)

    def test_cutover_state_blocks_accidental_legacy_fallback(self) -> None:
        # Behaviour is exercised end to end in test_dev_cutover_state.py.
        script = self.script()
        self.assertIn("/etc/mykhaya/dev/.service-env-state", script)
        self.assertNotIn(".service-env-active", script)
        guard = script[script.index("check_config_mode() {") : script.index("begin_transition() {")]
        self.assertIn("MYKHAYA_DEV_LEGACY_ENV_ROLLBACK", guard)
        for state in ("pending", "active", "rollback-pending"):
            self.assertIn(f"{state})", guard)
        # Fails fast, before any Docker interaction, and again before legacy .env use.
        preflight = script[script.index("preflight() {") : script.index("set_build_metadata()")]
        self.assertLess(preflight.index("check_config_mode"), preflight.index("docker info"))
        legacy = script[script.index("validate_env() {") :]
        self.assertLess(legacy.index("check_config_mode"), legacy.index('[ -f .env ] || die'))

    def test_state_transitions_bracket_container_recreation(self) -> None:
        script = self.script()
        deploy = script[script.index("deploy() {") : script.index("update() {")]
        begin = deploy.index("begin_transition")
        self.assertLess(deploy.index("validate_backend_config.py"), begin)
        self.assertLess(deploy.index("compose build"), begin)
        self.assertLess(begin, deploy.index("compose up -d --no-build postgres redis"))
        self.assertLess(deploy.index("health_checks"), deploy.index("complete_transition"))
        # Atomic replacement, in the state helper shared with production.
        self.assertIn('. "$SCRIPT_DIR/cutover-state.sh"', script)
        self.assertIn('cutover_write_state "$STATE_FILE" "$1"', script)
        helper = (ROOT / "infrastructure/scripts/cutover-state.sh").read_text(encoding="utf-8")
        self.assertIn('mv -f "$cutover_tmp" "$cutover_file"', helper)

    def test_local_compose_targets_are_guarded_on_the_dev_host(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8").replace("\r\n", "\n")
        guard = "\t@sh infrastructure/scripts/dev-host-guard.sh $@\n"
        for target in ("init", "up", "down", "backend-rebuild", "migrate", "reset"):
            recipe = makefile[makefile.index(f"\n{target}:\n") :]
            self.assertTrue(recipe.startswith(f"\n{target}:\n{guard}"), target)
        for target in ("dev-up", "dev-down", "test", "test-clean", "logs", "build"):
            recipe = makefile[makefile.index(f"\n{target}:\n") :].split("\n\n")[0]
            self.assertNotIn("dev-host-guard", recipe.split("\n", 3)[1], target)
        guard_script = (ROOT / "infrastructure/scripts/dev-host-guard.sh").read_text(encoding="utf-8")
        self.assertIn("/etc/mykhaya/dev/.service-env-state", guard_script)

    def test_service_env_root_must_be_absolute_and_is_never_prod(self) -> None:
        script = self.script()
        self.assertIn("MYKHAYA_DEV_CONFIG_ROOT must be an absolute path", script)
        self.assertNotIn("/etc/mykhaya/prod", script)
        self.assertNotIn("compose.production.yml", script)

    def test_config_check_touches_no_containers(self) -> None:
        script = self.script()
        block = script[script.index("  config-check)") : script.index("  migrate-networks) migrate_networks")]
        for forbidden in ("compose up", "compose stop", "compose build", "compose run", "git "):
            self.assertNotIn(forbidden, block)

    def test_new_deployment_inputs_are_change_controlled(self) -> None:
        script = self.script()
        self.assertIn("compose.dev.service-env.yml '.env.dev.*.example'", script)
        self.assertTrue((ROOT / "compose.dev.service-env.yml").is_file())
        self.assertTrue((ROOT / ".env.dev.compose.example").is_file())

    def test_caddy_preserves_proxy_headers_for_api(self) -> None:
        for relative in (
            "infrastructure/caddy/Caddyfile.dev",
            "infrastructure/caddy/Caddyfile.production",
        ):
            caddyfile = (ROOT / relative).read_text(encoding="utf-8")
            for header in (
                "header_up Host",
                "header_up X-Forwarded-Host",
                "header_up X-Forwarded-Proto",
                "header_up X-Forwarded-For",
            ):
                self.assertIn(header, caddyfile, relative)


if __name__ == "__main__":
    unittest.main()
