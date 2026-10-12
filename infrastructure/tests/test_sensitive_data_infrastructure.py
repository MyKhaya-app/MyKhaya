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
        update = self.deploy[self.deploy.index("update() {") :]
        update = update[: update.index("\n}\n")]
        first_change = min(
            update.index(marker)
            for marker in ("git fetch", "git checkout", "build", "run --rm", "up -d")
        )
        self.assertLess(update.index("backup_preflight"), first_change)
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

    def test_key_and_backup_material_is_gitignored(self) -> None:
        for pattern in ("/secrets/", "backups/", "*.age"):
            self.assertIn(pattern, self.gitignore.splitlines())


if __name__ == "__main__":
    unittest.main()
