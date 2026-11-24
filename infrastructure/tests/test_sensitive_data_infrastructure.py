"""Static guards for Phase 2A′ sensitive-data infrastructure invariants.

Behaviour of backup.sh/restore.sh is exercised end to end with real age
encryption outside CI (see docs/operations/backup-and-restore.md); these
tests pin the invariants that must never silently regress.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _service_block(compose: str, name: str) -> str:
    match = re.search(
        rf"^  {re.escape(name)}:(?: &\w+)?\n(.*?)(?=^  [a-z][\w-]*:(?: &\w+)?\n|^\S)",
        compose,
        re.M | re.S,
    )
    if match is None:
        raise AssertionError(f"service {name} not found")
    return match.group(1)


class SensitiveDataInfrastructureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.compose = (ROOT / "compose.yml").read_text(encoding="utf-8")
        cls.test_compose = (ROOT / "compose.test.yml").read_text(encoding="utf-8")
        cls.dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
        cls.web_dockerfile = (ROOT / "apps/web/Dockerfile").read_text(encoding="utf-8")
        cls.api_dockerfile = (ROOT / "apps/api/Dockerfile").read_text(encoding="utf-8")
        cls.backup = (ROOT / "infrastructure/scripts/backup.sh").read_text(encoding="utf-8")
        cls.restore = (ROOT / "infrastructure/scripts/restore.sh").read_text(encoding="utf-8")
        cls.gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        scripts = ROOT / "infrastructure/scripts"
        cls.restore_files = (scripts / "restore-files.sh").read_text(encoding="utf-8")
        cls.volumes = (scripts / "file-store-volumes.sh").read_text(encoding="utf-8")
        cls.preflight = (scripts / "backup-preflight.sh").read_text(encoding="utf-8")
        cls.deploy = (scripts / "prod-deploy.sh").read_text(encoding="utf-8")

    def test_deploy_runs_backup_preflight_before_any_change(self) -> None:
        validate = self.deploy[self.deploy.index("validate() {") :]
        self.assertIn("backup_preflight", validate[: validate.index("\n}\n")])
        update = self.deploy[self.deploy.index("\nupdate() {") :]
        update = update[: update.index("\n}\n")]
        first_change = min(update.index(marker) for marker in ("git fetch", "git checkout"))
        self.assertLess(update.index("backup_preflight"), first_change)
        # After the checkout, update re-executes the release's own script;
        # its validate() (which runs the preflight again) precedes every
        # build, migration and container change.
        self.assertIn("exec sh", update[update.index("git checkout") :])
        continued = self.deploy[self.deploy.index("continue_update() {") :]
        continued = continued[: continued.index("\n}\n")]
        first_change = min(continued.index(marker)
                           for marker in ("compose build", "run --rm", "up -d"))
        self.assertLess(continued.index("\n  validate\n"), first_change)
        self.assertIn("sh infrastructure/scripts/backup-preflight.sh", self.deploy)

    def test_preflight_covers_every_required_check(self) -> None:
        for marker in (
            "command -v age",
            "AGE-SECRET-KEY",
            "^age1[0-9a-z]\\{58\\}$",
            "writable by group/others",
            "backup directory is not writable",
            "MYKHAYA_BACKUP_AGE_IDENTITY",
        ):
            self.assertIn(marker, self.preflight)
        self.assertIn("exit 1", self.preflight)

    def test_file_stores_never_depend_on_the_api_container(self) -> None:
        for script in (self.backup, self.restore_files):
            self.assertNotIn("exec -T api", script)
            self.assertIn("file-store-volumes.sh", script)
            self.assertIn("--network none", script)
            self.assertIn("--read-only", script)
            self.assertIn("--cap-drop ALL", script)
            self.assertIn("--user 10001:10001", script)
        self.assertIn('[ "$mode" = ro ] && suffix=":ro"', self.volumes)
        self.assertIn("com.docker.compose.volume=$key", self.volumes)
        self.assertIn("file_store_volume_mounts ro", self.backup)

    def test_driveway_ciphertext_backfill_is_operator_run_only(self) -> None:
        """Phase 2C: never wired into deploy scripts, Compose or migrations."""
        candidates = [
            *ROOT.glob("compose*.yml"),
            ROOT / "Makefile",
            *(ROOT / "infrastructure").rglob("*.sh"),
            *(ROOT / "apps/api/migrations").rglob("*.py"),
        ]
        for path in candidates:
            self.assertNotIn(
                "driveway_ciphertext_backfill", path.read_text(encoding="utf-8"), str(path)
            )

    def test_postgres_never_receives_the_application_env_file(self) -> None:
        for compose, name in ((self.compose, "postgres"), (self.test_compose, "postgres-test")):
            block = _service_block(compose, name)
            self.assertNotRegex(block, r"(?m)^\s+env_file:", name)
            self.assertNotIn("/run/secrets", block, name)

    def test_field_keys_are_mounted_read_only_into_the_api_anchor_only(self) -> None:
        mount = ":/run/secrets/mykhaya:ro"
        self.assertEqual(self.compose.count(mount), 1)
        self.assertIn(mount, _service_block(self.compose, "api"))
        for name in ("migrate", "test", "web", "caddy", "postgres", "redis"):
            self.assertNotIn("/run/secrets", _service_block(self.compose, name), name)

    def test_services_without_key_access_blank_the_environment_fallback(self) -> None:
        for compose, name in ((self.compose, "migrate"), (self.compose, "test")):
            block = _service_block(compose, name)
            self.assertRegex(block, r'MYKHAYA_FIELD_ENCRYPTION_KEYS: ""', name)
            self.assertRegex(block, r'MYKHAYA_BLIND_INDEX_KEYS: ""', name)

    def test_services_without_apple_key_access_disable_and_blank_apple_settings(self) -> None:
        for name in ("migrate", "test"):
            block = _service_block(self.compose, name)
            self.assertRegex(block, r'MYKHAYA_APPLE_SIGN_IN_ENABLED: "false"', name)
            self.assertRegex(block, r'MYKHAYA_APPLE_PRIVATE_KEY: ""', name)
            self.assertRegex(block, r'MYKHAYA_APPLE_PRIVATE_KEY_FILE: ""', name)

    def test_syslog_debug_is_opt_in(self) -> None:
        self.assertNotIn('MYKHAYA_SYSLOG_DEBUG: "true"', self.compose)
        self.assertIn('MYKHAYA_SYSLOG_DEBUG: "${MYKHAYA_SYSLOG_DEBUG:-false}"', self.compose)

    def test_backup_encrypts_and_never_writes_plaintext_in_production(self) -> None:
        self.assertIn('age -R "$recipients_file"', self.backup)
        self.assertIn('fail "Backup encryption recipients are not configured."', self.backup)
        production_branch = self.backup[self.backup.index('if [ ! -f "$recipients_file" ]') :]
        production_branch = production_branch[: production_branch.index("fi\nif")]
        # The production refusal is checked before the plaintext opt-in.
        self.assertLess(
            production_branch.index('if [ "$production" = 1 ]'),
            production_branch.index('elif [ "$allow_plaintext" = 1 ]'),
        )
        self.assertIn("AGE-SECRET-KEY", self.backup)
        self.assertIn("MYKHAYA_BACKUP_AGE_IDENTITY", self.backup)

    def test_backup_covers_every_persistent_file_store_but_not_migration_packages(self) -> None:
        stores = re.search(r'^file_stores="([^"]+)"', self.backup, re.M)
        assert stores is not None
        self.assertEqual(
            set(stores.group(1).split()),
            {"avatars", "support-attachments", "vehicle-photos", "meal-images"},
        )
        self.assertNotIn("home-migrations", stores.group(1))

    def test_backup_checks_each_producer_status(self) -> None:
        self.assertIn('echo $? > "$status_dir/pg_dump"', self.backup)
        self.assertIn('echo $? > "$status_dir/tar"', self.backup)

    def test_restore_requires_an_identity_for_encrypted_backups(self) -> None:
        self.assertIn("MYKHAYA_BACKUP_AGE_IDENTITY", self.restore)
        self.assertIn("age -d -i", self.restore)

    def test_containers_never_copy_secret_files_into_the_environment(self) -> None:
        """MK-SEC-001 SEC-093: application secret files are read in-process by
        the central registry (apps/api/mykhaya/secret_registry.py). No image
        or shell script may read /run/secrets and export the value instead."""
        candidates = [
            *ROOT.glob("apps/*/Dockerfile"),
            *ROOT.glob("infrastructure/**/*.sh"),
            *ROOT.glob("infrastructure/**/Dockerfile*"),
            *ROOT.glob("apps/*/*entrypoint*"),
            *ROOT.glob("infrastructure/**/*entrypoint*"),
        ]
        self.assertIn(ROOT / "apps/api/Dockerfile", candidates)
        # Explicit exceptions, each reviewed (MK-SEC-001 WP-4):
        allowed = {
            # The PostgreSQL bootstrap reads its own password files and hands
            # them to psql on standard input; it never exports them.
            "infrastructure/docker/init-db.sh",
            # The CI check mounts synthetic secrets into disposable containers.
            "infrastructure/scripts/check-phase1-secrets.sh",
        }
        offenders = sorted(
            path.relative_to(ROOT).as_posix()
            for path in candidates
            if path.is_file()
            and "/run/secrets" in path.read_text(encoding="utf-8", errors="replace")
            and path.relative_to(ROOT).as_posix() not in allowed
        )
        self.assertEqual(offenders, [])
        bootstrap = (ROOT / "infrastructure/docker/init-db.sh").read_text(encoding="utf-8")
        self.assertNotRegex(bootstrap, r"(?m)^\s*(export|declare\s+-x)\b")

    def test_key_and_backup_material_is_gitignored(self) -> None:
        for pattern in ("/secrets/", "backups/", "*.age"):
            self.assertIn(pattern, self.gitignore.splitlines())

    def test_dockerignore_excludes_local_sensitive_material(self) -> None:
        lines = set(self.dockerignore.splitlines())
        for pattern in (
            ".env",
            ".env.*",
            "!.env.example",
            "secrets/",
            "backups/",
            "**/*.pem",
            "**/*.p8",
            "**/*firebase-adminsdk-*.json",
            "**/google-services.json",
            "*.sql",
            "*.sql.gz",
            "*.dump",
            "*.bak",
            "**/node_modules/",
            "**/.next/",
            "**/test-results/",
            "**/coverage/",
            "**/__pycache__/",
            "**/.pytest_cache/",
            "**/.ruff_cache/",
        ):
            self.assertIn(pattern, lines)

    def test_dockerignore_preserves_all_explicit_dockerfile_inputs(self) -> None:
        required_inputs = (
            "package.json",
            "pnpm-lock.yaml",
            "pnpm-workspace.yaml",
            "packages",
            "apps/web",
            "apps/web/public",
            "apps/web/public/fonts/marketing/",
            "apps/web/public/images/marketing/mykhaya-logo-256.png",
            "apps/api/pyproject.toml",
            "apps/api/mykhaya",
            "apps/api/tests",
            "apps/api/migrations",
            "packages/design-tokens",
            "apps/api/alembic.ini",
            "docs",
        )
        for required in required_inputs:
            self.assertTrue((ROOT / required.rstrip("/")).exists(), required)
        self.assertIn("COPY apps/web ./apps/web", self.web_dockerfile)
        self.assertIn("/workspace/apps/web/public ./apps/web/public", self.web_dockerfile)
        self.assertIn("COPY apps/api/mykhaya ./mykhaya", self.api_dockerfile)
        self.assertIn("COPY apps/api/migrations ./migrations", self.api_dockerfile)
        self.assertIn("COPY docs ./docs", self.api_dockerfile)


if __name__ == "__main__":
    unittest.main()
