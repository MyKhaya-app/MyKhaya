"""F-03 Stage 3A: DEV service-specific configuration contract and overlay.

Every configuration value here is synthetic (synthetic_dev_config.py). The
Compose models are inspected in memory and never printed.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import synthetic_dev_config as synthetic  # noqa: E402

SPEC = importlib.util.spec_from_file_location(
    "service_env_contract", ROOT / "infrastructure/scripts/service_env_contract.py"
)
assert SPEC is not None and SPEC.loader is not None
contract = importlib.util.module_from_spec(SPEC)
sys.modules["service_env_contract"] = contract
SPEC.loader.exec_module(contract)

POSIX = os.name == "posix"
SECRETS = (synthetic.SECRET_KEY, synthetic.ADMIN_PASSWORD, synthetic.MIGRATION_PASSWORD,
           synthetic.RUNTIME_PASSWORD, "sk_live_synthetic", "synthetic-stripe-secret")
DEV_FILES = ("-f", "compose.yml", "-f", "compose.dev.yml")
OVERLAY = ("-f", "compose.dev.service-env.yml")


def docker_compose_available() -> bool:
    if shutil.which("docker") is None:
        return False
    return subprocess.run(["docker", "compose", "version"], capture_output=True).returncode == 0


def trusted_probe(source: str) -> contract.KeyDirListing:
    """Stands in for the Docker key-directory probe (test_key_directory_probe.py
    exercises the real one): the real entries, with correctly provisioned
    ownership and modes as the service identity would see them."""
    path = Path(source)
    entries = []
    for child in sorted(path.iterdir()):
        kind = ("symlink" if child.is_symlink() else "directory" if child.is_dir()
                else "file" if child.is_file() else "other")
        entries.append(contract.KeyEntry(child.name, kind, 0o440, 0, contract.SERVICE_GID,
                                         child.lstat().st_ino, kind == "file"))
    root = contract.KeyEntry(".", "directory", 0o750, 0, contract.SERVICE_GID,
                             path.lstat().st_ino, True)
    return contract.KeyDirListing(contract.SERVICE_UID, contract.SERVICE_GID,
                                  (contract.SERVICE_GID,), root, tuple(entries))


class SyntheticRoot:
    def __init__(self) -> None:
        self.base = Path(tempfile.mkdtemp(prefix="mykhaya-f03-3a-"))
        self.root = synthetic.write_synthetic_root(self.base)

    def edit(self, name: str, *, add: str = "", remove: str | None = None,
             replace: tuple[str, str] | None = None) -> None:
        path = self.root / name
        text = path.read_text(encoding="utf-8")
        if remove:
            text = "".join(l for l in text.splitlines(keepends=True) if not l.startswith(remove + "="))
        if replace:
            text = text.replace(*replace)
        path.write_text(text + add, encoding="utf-8", newline="\n")

    def validate(self) -> contract.Report:
        return contract.validate_root(self.root, repo_root=ROOT, check_perms=POSIX,
                                      probe=trusted_probe)

    def cleanup(self) -> None:
        shutil.rmtree(self.base, ignore_errors=True)


class StaticContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cfg = SyntheticRoot()
        self.addCleanup(self.cfg.cleanup)

    def assertRejected(self, fragment: str) -> list[str]:
        report = self.cfg.validate()
        joined = "\n".join(report.errors + report.warnings)
        self.assertTrue(any(fragment in e for e in report.errors), joined)
        for secret in SECRETS:
            self.assertNotIn(secret, joined)
        return report.errors

    def test_complete_synthetic_root_passes(self):
        report = self.cfg.validate()
        self.assertEqual(report.errors, [])

    def test_unfilled_templates_cannot_be_deployed(self):
        for template, name in (("api", "api.env"), ("worker", "worker.env"),
                               ("scheduler", "scheduler.env"), ("migrate", "migrate.env"),
                               ("postgres", "postgres.env"), ("compose", "compose.env")):
            shutil.copyfile(ROOT / f".env.dev.{template}.example", self.cfg.root / name)
        self.assertRejected("still contains a documented placeholder")

    def test_templates_respect_their_own_contracts(self):
        for contract_file in contract.CONTRACTS:
            template = ROOT / f".env.dev.{contract_file.name.removesuffix('.env')}.example"
            values, problems = contract.parse_env_file(template)
            report = contract.Report()
            contract.check_contract(contract_file, values, report)
            self.assertEqual(problems, [], template.name)
            errors = [e for e in report.errors if "placeholder" not in e]
            self.assertEqual(errors, [], template.name)

    def test_worker_cannot_receive_stripe_or_oauth_secrets(self):
        self.cfg.edit("worker.env", add="MYKHAYA_STRIPE_SECRET_KEY=synthetic-stripe-secret\n"
                                        "MYKHAYA_GOOGLE_CLIENT_SECRET=synthetic\n")
        errors = self.assertRejected("MYKHAYA_STRIPE_SECRET_KEY must not be supplied")
        self.assertTrue(any("MYKHAYA_GOOGLE_CLIENT_SECRET must not" in e for e in errors))

    def test_api_cannot_receive_apns_or_watchdog(self):
        self.cfg.edit("api.env", add="MYKHAYA_APNS_PRIVATE_KEY=x\nMYKHAYA_MONITORING_WATCHDOG_URL=x\n")
        errors = self.assertRejected("MYKHAYA_APNS_PRIVATE_KEY must not be supplied")
        self.assertTrue(any("MYKHAYA_MONITORING_WATCHDOG_URL must not" in e for e in errors))

    def test_application_services_cannot_receive_bootstrap_passwords(self):
        for name in ("api.env", "worker.env", "scheduler.env", "migrate.env", "common.env"):
            with self.subTest(name=name):
                cfg = SyntheticRoot()
                self.addCleanup(cfg.cleanup)
                cfg.edit(name, add="MYKHAYA_DB_PASSWORD=x\n")
                report = cfg.validate()
                self.assertTrue(any("MYKHAYA_DB_PASSWORD must not be supplied" in e
                                    for e in report.errors), report.errors)

    def test_migrate_receives_only_url_and_compatibility_secret(self):
        self.cfg.edit("migrate.env", add="MYKHAYA_REDIS_URL=redis://redis:6379/0\n"
                                         "MYKHAYA_SMTP_PASSWORD=x\n")
        errors = self.assertRejected("MYKHAYA_REDIS_URL must not be supplied")
        self.assertTrue(any("MYKHAYA_SMTP_PASSWORD must not" in e for e in errors))

    def test_compose_interpolation_file_rejects_credentials(self):
        self.cfg.edit("compose.env", add="MYKHAYA_DB_PASSWORD=x\nMYKHAYA_SECRET_KEY=x\n")
        self.assertRejected("compose.env: MYKHAYA_DB_PASSWORD must not be supplied")

    def test_pinned_values_are_rejected_in_service_files(self):
        self.cfg.edit("api.env", add="MYKHAYA_PUBLIC_WEB_URL=https://dev.mykhaya.app\n")
        self.cfg.edit("common.env", add="MYKHAYA_ENVIRONMENT=development\n")
        self.assertRejected("MYKHAYA_PUBLIC_WEB_URL is pinned by compose.dev.yml")

    def test_unknown_variables_are_rejected(self):
        self.cfg.edit("scheduler.env", add="MYKHAYA_SMTP_STARTTLS=false\n")
        self.assertRejected("MYKHAYA_SMTP_STARTTLS is not part of this file's contract")

    def test_missing_required_file_and_variable_fail(self):
        (self.cfg.root / "worker.env").unlink()
        self.cfg.edit("api.env", remove="MYKHAYA_SECRET_KEY")
        errors = self.assertRejected("worker.env: required file is missing")
        self.assertTrue(any("api.env: required variable MYKHAYA_SECRET_KEY" in e for e in errors))

    def test_database_passwords_must_match_postgres_bootstrap(self):
        self.cfg.edit("api.env", replace=(synthetic.RUNTIME_PASSWORD, "different-runtime"))
        self.cfg.edit("migrate.env", replace=(synthetic.MIGRATION_PASSWORD, "different-migration"))
        errors = self.assertRejected("api.env: MYKHAYA_DATABASE_URL password does not match")
        self.assertTrue(any("migrate.env: MYKHAYA_DATABASE_URL password does not match" in e
                            for e in errors))
        self.assertTrue(all("different-runtime" not in e for e in errors))

    def test_database_roles_are_enforced(self):
        self.cfg.edit("migrate.env", replace=("mykhaya_migrator", "mykhaya_app"))
        self.cfg.edit("worker.env", replace=("mykhaya_app", "mykhaya_migrator"))
        errors = self.assertRejected("migrate.env: MYKHAYA_DATABASE_URL must use the mykhaya_migrator")
        self.assertTrue(any("worker.env: MYKHAYA_DATABASE_URL must use the mykhaya_app" in e
                            for e in errors))

    def test_secret_key_must_be_identical(self):
        self.cfg.edit("scheduler.env", replace=(synthetic.SECRET_KEY, synthetic.SECRET_KEY + "x"))
        self.assertRejected("MYKHAYA_SECRET_KEY differs between service files")

    def test_provider_groups_must_match_api(self):
        stripe = ("MYKHAYA_STRIPE_BILLING_CONFIGURED=true\nMYKHAYA_STRIPE_SECRET_KEY={k}\n"
                  "MYKHAYA_STRIPE_WEBHOOK_SECRET=w\nMYKHAYA_STRIPE_FAMILY_MONTHLY_PRICE_ID=m\n"
                  "MYKHAYA_STRIPE_FAMILY_ANNUAL_PRICE_ID=a\n")
        self.cfg.edit("api.env", remove="MYKHAYA_STRIPE_BILLING_CONFIGURED",
                      add=stripe.format(k="synthetic-stripe-secret"))
        self.cfg.edit("scheduler.env", add=stripe.format(k="synthetic-stripe-secret"))
        self.assertEqual(self.cfg.validate().errors, [])
        self.cfg.edit("scheduler.env", replace=("synthetic-stripe-secret", "synthetic-stripe-secret2"))
        self.assertRejected("scheduler.env: MYKHAYA_STRIPE_SECRET_KEY differs from api.env")

    def test_dev_production_separation_markers(self):
        self.cfg.edit("api.env", remove="MYKHAYA_STRIPE_BILLING_CONFIGURED",
                      add="MYKHAYA_STRIPE_SECRET_KEY=sk_live_synthetic\n"
                          "MYKHAYA_FCM_PROJECT_ID=mykhaya-prod\n")
        self.cfg.edit("worker.env", replace=("app.mykhaya.mobile", "app.mykhaya.mobile.prod"))
        errors = self.assertRejected("live-mode key")
        self.assertTrue(any("production Firebase project" in e for e in errors))
        self.assertTrue(any("production iOS app" in e for e in errors))

    def test_dev_is_not_forced_onto_dvla_uat(self):
        dvla = ("MYKHAYA_DVLA_ENVIRONMENT=production\n"
                "MYKHAYA_DVLA_PRODUCTION_ENDPOINT=https://dvla.invalid/v1\n"
                "MYKHAYA_DVLA_PRODUCTION_API_KEY=synthetic\n")
        self.cfg.edit("api.env", remove="MYKHAYA_DVLA_ENVIRONMENT", add=dvla)
        self.cfg.edit("scheduler.env", add=dvla)
        self.assertEqual(self.cfg.validate().errors, [])

    def test_scheduler_gets_only_the_selected_dvla_environment(self):
        dvla = ("MYKHAYA_DVLA_ENVIRONMENT=production\n"
                "MYKHAYA_DVLA_PRODUCTION_ENDPOINT=https://dvla.invalid/v1\n"
                "MYKHAYA_DVLA_PRODUCTION_API_KEY=synthetic-dvla\n")
        self.cfg.edit("api.env", remove="MYKHAYA_DVLA_ENVIRONMENT",
                      add=dvla + "MYKHAYA_DVLA_UAT_API_KEY=synthetic-uat\n")
        self.cfg.edit("scheduler.env", add=dvla)
        self.assertEqual(self.cfg.validate().errors, [])  # DEV keeps production DVLA
        self.cfg.edit("scheduler.env", add="MYKHAYA_DVLA_UAT_API_KEY=synthetic-uat\n")
        self.assertRejected("scheduler.env: MYKHAYA_DVLA_UAT_API_KEY is not used by the selected")

    def test_monitoring_cannot_silently_become_not_applicable(self):
        dvla = ("MYKHAYA_DVLA_ENVIRONMENT=production\n"
                "MYKHAYA_DVLA_PRODUCTION_ENDPOINT=https://dvla.invalid/v1\n"
                "MYKHAYA_DVLA_PRODUCTION_API_KEY=synthetic-dvla\n")
        self.cfg.edit("api.env", remove="MYKHAYA_DVLA_ENVIRONMENT", add=dvla)
        self.cfg.edit("api.env", replace=("MYKHAYA_APPLE_SIGN_IN_ENABLED=false",
                                          "MYKHAYA_APPLE_SIGN_IN_ENABLED=true"))
        self.cfg.edit("scheduler.env", remove="MYKHAYA_SMTP_PASSWORD")
        self.cfg.edit("scheduler.env", remove="MYKHAYA_SMTP_HOST")
        errors = self.assertRejected("scheduler.env: MYKHAYA_DVLA_PRODUCTION_API_KEY is missing; "
                                     "DVLA is configured through api.env")
        self.assertTrue(any("MYKHAYA_SMTP_HOST is missing; SMTP" in e for e in errors), errors)
        self.assertTrue(any("MYKHAYA_APPLE_SIGN_IN_ENABLED" in e and "Apple" in e for e in errors))

    def test_scheduler_dvsa_access_is_limited_to_monitoring_inputs(self):
        self.cfg.edit("scheduler.env", add="MYKHAYA_DVSA_SCOPE=x\nMYKHAYA_DVSA_ENVIRONMENT=production\n")
        errors = self.assertRejected("scheduler.env: MYKHAYA_DVSA_SCOPE is not part of this file's contract")
        self.assertTrue(any("MYKHAYA_DVSA_ENVIRONMENT is not part" in e for e in errors))

    def test_production_and_repository_roots_are_refused(self):
        report = contract.Report()
        contract.check_root_location(Path("/etc/mykhaya/prod"), ROOT, report)
        self.assertTrue(any("production path" in e for e in report.errors))
        report = contract.Report()
        contract.check_root_location(ROOT / "infrastructure", ROOT, report)
        self.assertTrue(any("inside the repository" in e for e in report.errors))
        self.assertTrue(contract._is_production_path("/srv/mykhaya/production/config"))
        self.assertFalse(contract._is_production_path("/etc/mykhaya/dev"))

    def test_secret_directories_must_exist_outside_repo_and_prod(self):
        self.cfg.edit("compose.env", replace=(
            (self.cfg.base / "secrets" / "apple").as_posix(), "/etc/mykhaya/prod/apple"))
        self.assertRejected("MYKHAYA_APPLE_KEY_HOST_DIR points at a production path")
        cfg = SyntheticRoot()
        self.addCleanup(cfg.cleanup)
        shutil.rmtree(cfg.base / "secrets" / "field-keys")
        report = cfg.validate()
        self.assertTrue(any("MYKHAYA_FIELD_KEYS_HOST_DIR does not exist" in e for e in report.errors))

    def test_key_file_paths_must_be_inside_read_only_mounts(self):
        self.cfg.edit("common.env", add="MYKHAYA_FIELD_ENCRYPTION_KEYS_FILE=/tmp/keys.json\n")
        self.assertRejected("must be inside the read-only /run/secrets/mykhaya/ mount")

    def test_test_configuration_never_lives_in_the_dev_root(self):
        (self.cfg.root / "test.env").write_text("MYKHAYA_ENVIRONMENT=test\n", encoding="utf-8")
        self.assertRejected("test.env: is not a recognised DEV configuration file")

    def test_interpolating_dollar_values_are_refused_without_disclosure(self):
        # Compose would interpolate $secret (to empty), silently changing the value.
        self.cfg.edit("api.env", add="MYKHAYA_SMTP_PASSWORD=synthetic$secret\n")
        self.cfg.edit("worker.env", add="MYKHAYA_SMTP_PASSWORD='synthetic$secret'\n")
        errors = self.assertRejected("api.env line")
        self.assertTrue(any("MYKHAYA_SMTP_PASSWORD contains '$' that Compose would interpolate" in e
                            for e in errors))
        self.assertFalse(any("worker.env" in e and "interpolate" in e for e in errors))
        self.assertTrue(all("synthetic" not in e for e in errors))

    @unittest.skipUnless(POSIX, "POSIX permission semantics")
    def test_world_readable_secret_files_and_links_are_refused(self):
        os.chmod(self.cfg.root / "api.env", 0o644)
        errors = self.assertRejected("api.env: is readable by other users")
        (self.cfg.root / "worker.env").unlink()
        (self.cfg.root / "worker.env").symlink_to(self.cfg.root / "api.env")
        self.assertTrue(any("worker.env: must be a regular file" in e
                            for e in self.cfg.validate().errors), errors)

    def test_permission_logic_with_synthetic_modes(self):
        class Info:
            def __init__(self, mode):
                self.st_mode, self.st_uid = 0o100000 | mode, os.geteuid() if hasattr(os, "geteuid") else 0

        class FakePath:
            name = "fake.env"

            def __init__(self, mode):
                self.mode = mode

            def lstat(self):
                return Info(self.mode)

        for mode, expected in ((0o600, None), (0o640, None), (0o644, "readable by other"),
                               (0o660, "writable by its group"), (0o602, "writable by other")):
            report = contract.Report()
            contract.check_permissions(FakePath(mode), secret=True, is_dir=False, report=report)
            if expected is None:
                self.assertEqual(report.errors, [], oct(mode))
            else:
                self.assertTrue(any(expected in e for e in report.errors), (oct(mode), report.errors))


class LegacySplitTests(unittest.TestCase):
    """The migration aid that turns the legacy DEV .env into service files."""

    def legacy_env(self, directory: Path) -> Path:
        cfg = SyntheticRoot()
        self.addCleanup(cfg.cleanup)
        merged: dict[str, str] = {}
        for name in ("compose.env", "common.env", "api.env", "worker.env", "scheduler.env"):
            merged.update(contract.parse_env_file(cfg.root / name)[0])
        merged.pop("MYKHAYA_DATABASE_URL")
        merged.update({
            "MYKHAYA_POSTGRES_ADMIN_PASSWORD": synthetic.ADMIN_PASSWORD,
            "MYKHAYA_MIGRATION_DB_PASSWORD": synthetic.MIGRATION_PASSWORD,
            "MYKHAYA_DB_PASSWORD": synthetic.RUNTIME_PASSWORD,
            # Present in real legacy files: pinned, obsolete or environment-configured.
            "MYKHAYA_PUBLIC_WEB_URL": "https://dev.mykhaya.app",
            "MYKHAYA_ENVIRONMENT": "development",
            "MYKHAYA_SMTP_STARTTLS": "false",
            "MYKHAYA_SMTP_PASSWORD": "synthetic-smtp-secret",
            "MYKHAYA_MONITORING_WATCHDOG_URL": "https://watchdog.invalid/synthetic-ping",
            "MYKHAYA_APNS_DELIVERY_CONFIGURED": "false",
        })
        path = directory / "legacy.env"
        path.write_text("".join(f"{k}={v}\n" for k, v in merged.items()), encoding="utf-8")
        self.cfg = cfg
        return path

    def run_split(self):
        work = Path(tempfile.mkdtemp(prefix="mykhaya-f03-split-"))
        self.addCleanup(shutil.rmtree, work, True)
        legacy = self.legacy_env(work)
        out = work / "dev"
        out.mkdir()
        os.chmod(out, 0o750)
        import contextlib
        import io
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = contract.main(["--split-legacy-env", str(legacy), "--out", str(out)])
        return code, buffer.getvalue(), out, legacy

    def test_split_output_passes_the_contract(self):
        code, output, out, _ = self.run_split()
        self.assertEqual(code, 0)
        report = contract.validate_root(out, repo_root=ROOT, check_perms=POSIX,
                                        probe=trusted_probe)
        self.assertEqual(report.errors, [])

    def test_split_never_prints_values_and_reports_names(self):
        _, output, _, _ = self.run_split()
        for secret in (*SECRETS, "synthetic-smtp-secret", "synthetic-ping"):
            self.assertNotIn(secret, output)
        self.assertIn("pinned (no effect today; dropped): MYKHAYA_ENVIRONMENT, MYKHAYA_PUBLIC_WEB_URL",
                      output)
        self.assertIn("not a setting or Compose input (dropped): MYKHAYA_SMTP_STARTTLS", output)

    def test_split_places_credentials_only_with_their_consumers(self):
        _, output, out, _ = self.run_split()
        files = {p.name: contract.parse_env_file(p)[0] for p in out.iterdir()}
        self.assertIn("MYKHAYA_MONITORING_WATCHDOG_URL", files["scheduler.env"])
        self.assertNotIn("MYKHAYA_MONITORING_WATCHDOG_URL", files["api.env"])
        self.assertIn("MYKHAYA_APNS_DELIVERY_CONFIGURED", files["worker.env"])
        self.assertNotIn("MYKHAYA_APNS_DELIVERY_CONFIGURED", files["api.env"])
        for name in ("api.env", "worker.env", "scheduler.env"):
            self.assertEqual(files[name]["MYKHAYA_SMTP_PASSWORD"], "synthetic-smtp-secret", name)
        self.assertEqual(set(files["migrate.env"]), {"MYKHAYA_DATABASE_URL", "MYKHAYA_SECRET_KEY"})
        self.assertEqual(files["postgres.env"]["POSTGRES_PASSWORD"], synthetic.ADMIN_PASSWORD)
        self.assertEqual(files["api.env"]["MYKHAYA_DATABASE_URL"],
                         contract.LEGACY_APP_URL.format(synthetic.RUNTIME_PASSWORD))
        lines = dict(line.split(": ", 1) for line in output.splitlines() if ": " in line)
        api_dropped = set(lines["no longer delivered to api"].split(", "))
        # Real changes only: bootstrap passwords and the scheduler-only watchdog.
        self.assertIn("MYKHAYA_DB_PASSWORD", api_dropped)
        self.assertIn("MYKHAYA_MONITORING_WATCHDOG_URL", api_dropped)
        # APNs was already pinned blank for api by compose.yml: not a change.
        self.assertNotIn("MYKHAYA_APNS_DELIVERY_CONFIGURED", api_dropped)
        worker_dropped = set(lines["no longer delivered to worker"].split(", "))
        self.assertIn("MYKHAYA_STRIPE_BILLING_CONFIGURED", worker_dropped)

    def test_split_gives_scheduler_only_the_selected_dvla_pair(self):
        files, _ = contract.split_legacy_env({
            "MYKHAYA_DVLA_ENVIRONMENT": "production",
            "MYKHAYA_DVLA_PRODUCTION_ENDPOINT": "https://dvla.invalid/v1",
            "MYKHAYA_DVLA_PRODUCTION_API_KEY": "p",
            "MYKHAYA_DVLA_UAT_ENDPOINT": "https://uat.invalid/v1",
            "MYKHAYA_DVLA_UAT_API_KEY": "u",
            "MYKHAYA_DVSA_SCOPE": "s",
        })
        self.assertEqual(set(files["scheduler.env"]), {
            "MYKHAYA_DVLA_ENVIRONMENT", "MYKHAYA_DVLA_PRODUCTION_ENDPOINT",
            "MYKHAYA_DVLA_PRODUCTION_API_KEY"})
        self.assertIn("MYKHAYA_DVLA_UAT_API_KEY", files["api.env"])  # API unchanged
        self.assertIn("MYKHAYA_DVSA_SCOPE", files["api.env"])

    def test_split_refuses_to_overwrite(self):
        _, _, out, legacy = self.run_split()
        with self.assertRaises(SystemExit) as raised:
            contract.main(["--split-legacy-env", str(legacy), "--out", str(out)])
        self.assertIn("refusing to overwrite", str(raised.exception))

    @unittest.skipUnless(POSIX, "POSIX permission semantics")
    def test_split_files_are_created_with_restrictive_modes(self):
        _, _, out, _ = self.run_split()
        for path in out.iterdir():
            expected = 0o640 if path.name in {"compose.env", "common.env"} else 0o600
            self.assertEqual(path.stat().st_mode & 0o777, expected, path.name)


@unittest.skipUnless(docker_compose_available(), "Docker Compose is required")
class ComposeModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cfg = SyntheticRoot()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.cfg.cleanup()

    def compose(self, *args: str, root: Path | None = None, overlay: bool = True):
        root = root or self.cfg.root
        env = dict(os.environ, MYKHAYA_DEV_CONFIG_ROOT=str(root), MYKHAYA_DB_PASSWORD="",
                   MYKHAYA_MIGRATION_DB_PASSWORD="", MYKHAYA_POSTGRES_ADMIN_PASSWORD="",
                   MSYS_NO_PATHCONV="1")
        command = ["docker", "compose", "--env-file", str(root / "compose.env"), *DEV_FILES,
                   *(OVERLAY if overlay else ()), "--profile", "tools", *args]
        return subprocess.run(command, cwd=ROOT, capture_output=True, text=True, env=env)

    def model(self) -> dict:
        result = self.compose("config", "--format", "json")
        self.assertEqual(result.returncode, 0, contract_safe(result.stderr))
        return json.loads(result.stdout)

    def paired_models(self) -> tuple[dict, dict, set[str]]:
        """Legacy and service-env models resolved from identical synthetic inputs.

        Works on any Compose version (no --no-interpolate). Both run in a
        throwaway project directory, so the legacy env_file `.env` is a
        synthetic file holding only names no service declares; those names are
        returned so they can be subtracted from the legacy model exactly.
        """
        project = Path(tempfile.mkdtemp(prefix="mykhaya-f03-legacy-"))
        self.addCleanup(shutil.rmtree, project, True)
        keys = {k: v for k, v in contract.parse_env_file(self.cfg.root / "compose.env")[0].items()
                if k in {"MYKHAYA_FIELD_KEYS_HOST_DIR", "MYKHAYA_APPLE_KEY_HOST_DIR"}}
        interpolation = {**keys, "MYKHAYA_DB_PASSWORD": synthetic.RUNTIME_PASSWORD,
                         "MYKHAYA_MIGRATION_DB_PASSWORD": synthetic.MIGRATION_PASSWORD,
                         "MYKHAYA_POSTGRES_ADMIN_PASSWORD": synthetic.ADMIN_PASSWORD}
        (project / ".env").write_text("".join(f"{k}={v}\n" for k, v in interpolation.items()),
                                      encoding="utf-8", newline="\n")
        (project / "split.env").write_text("".join(f"{k}={v}\n" for k, v in keys.items()),
                                           encoding="utf-8", newline="\n")
        shutil.copyfile(ROOT / ".env.dev.test.example", project / ".env.dev.test.example")
        files = [arg if not arg.endswith(".yml") else str(ROOT / arg) for arg in DEV_FILES]
        base = dict(os.environ, MSYS_NO_PATHCONV="1")
        base.pop("MYKHAYA_DEV_CONFIG_ROOT", None)
        legacy = subprocess.run(
            ["docker", "compose", "--project-directory", str(project), *files, "--profile",
             "tools", "config", "--format", "json"],
            capture_output=True, text=True, env=base)
        self.assertEqual(legacy.returncode, 0, contract_safe(legacy.stderr))
        split = subprocess.run(
            ["docker", "compose", "--project-directory", str(project), "--env-file",
             str(project / "split.env"), *files, "-f", str(ROOT / OVERLAY[1]), "--profile",
             "tools", "config", "--format", "json"],
            capture_output=True, text=True,
            env=dict(base, MYKHAYA_DEV_CONFIG_ROOT=str(self.cfg.root), MYKHAYA_DB_PASSWORD="",
                     MYKHAYA_MIGRATION_DB_PASSWORD="", MYKHAYA_POSTGRES_ADMIN_PASSWORD=""))
        self.assertEqual(split.returncode, 0, contract_safe(split.stderr))
        return json.loads(legacy.stdout), json.loads(split.stdout), set(interpolation)

    def test_merged_model_matches_contract(self):
        self.assertEqual(contract.check_resolved_model(self.model(), ROOT), [])

    def test_env_file_provenance_is_the_dev_root_only(self):
        self.assertEqual(contract.check_provenance(self.model(), self.cfg.root), [])

    def test_provenance_detects_any_extra_configuration_source(self):
        extra = self.cfg.base / "extra.yml"
        extra.write_text(
            "services:\n  worker:\n    environment:\n      MYKHAYA_STRIPE_SECRET_KEY: leaked\n"
            "  api:\n    environment:\n      MYKHAYA_SMTP_HOST: other-source\n",
            encoding="utf-8")
        self.addCleanup(extra.unlink)
        result = self.compose("-f", str(extra), "config", "--format", "json")
        self.assertEqual(result.returncode, 0, contract_safe(result.stderr))
        errors = contract.check_provenance(json.loads(result.stdout), self.cfg.root)
        self.assertIn("worker: receives MYKHAYA_STRIPE_SECRET_KEY from outside "
                      "MYKHAYA_DEV_CONFIG_ROOT", errors)
        self.assertIn("api: MYKHAYA_SMTP_HOST differs from its file (another source wins)", errors)
        self.assertTrue(all("leaked" not in e and "other-source" not in e for e in errors))

    def test_service_values_come_from_the_service_files(self):
        services = self.model()["services"]
        api_values, _ = contract.parse_env_file(self.cfg.root / "api.env")
        migrate_values, _ = contract.parse_env_file(self.cfg.root / "migrate.env")
        pg_values, _ = contract.parse_env_file(self.cfg.root / "postgres.env")
        for name in ("api", "worker", "scheduler"):
            self.assertEqual(services[name]["environment"]["MYKHAYA_DATABASE_URL"],
                             api_values["MYKHAYA_DATABASE_URL"], name)
        self.assertEqual(services["migrate"]["environment"]["MYKHAYA_DATABASE_URL"],
                         migrate_values["MYKHAYA_DATABASE_URL"])
        self.assertEqual(services["postgres"]["environment"]["POSTGRES_PASSWORD"],
                         pg_values["POSTGRES_PASSWORD"])
        # compose.dev.yml pins still win over every service file.
        self.assertEqual(services["api"]["environment"]["MYKHAYA_PUBLIC_WEB_URL"],
                         "https://dev.mykhaya.app")
        self.assertEqual(services["worker"]["environment"]["MYKHAYA_APNS_BUNDLE_ID"],
                         "app.mykhaya.mobile")

    def test_missing_root_variable_fails_closed(self):
        env = {k: v for k, v in os.environ.items() if k != "MYKHAYA_DEV_CONFIG_ROOT"}
        result = subprocess.run(
            ["docker", "compose", "--env-file", str(self.cfg.root / "compose.env"), *DEV_FILES,
             *OVERLAY, "config", "--quiet"], cwd=ROOT, capture_output=True, text=True, env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("MYKHAYA_DEV_CONFIG_ROOT", result.stderr)

    def test_missing_service_file_fails_closed(self):
        cfg = SyntheticRoot()
        self.addCleanup(cfg.cleanup)
        (cfg.root / "scheduler.env").unlink()
        result = self.compose("config", "--quiet", root=cfg.root)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("scheduler.env", result.stderr)

    def test_hardening_and_runtime_behaviour_match_legacy(self):
        legacy, split, _ = self.paired_models()
        legacy, split = legacy["services"], split["services"]
        self.assertEqual(set(legacy), set(split))
        keys = ("read_only", "cap_drop", "cap_add", "security_opt", "tmpfs", "restart",
                "logging", "healthcheck", "networks", "stop_grace_period", "user", "command",
                "depends_on", "ports", "profiles", "build", "image")
        for name in legacy:
            for key in keys:
                self.assertEqual(split[name].get(key), legacy[name].get(key), f"{name}.{key}")
        for name in ("api", "worker", "scheduler", "web", "caddy", "test"):
            self.assertTrue(split[name].get("read_only"), name)
        for name, service in split.items():
            self.assertIn("no-new-privileges:true", service.get("security_opt", []), name)
            self.assertEqual(service.get("cap_drop"), ["ALL"], name)
        self.assertEqual(split["worker"]["healthcheck"], {"disable": True})
        self.assertEqual(split["scheduler"]["healthcheck"], {"disable": True})

    def test_environment_matches_legacy_except_secret_interpolations(self):
        """The overlay restates compose.yml + compose.dev.yml exactly, minus
        values interpolated from secrets, which now come from the files."""
        legacy, split, dotenv_names = self.paired_models()
        removed = {
            "api": {"MYKHAYA_DATABASE_URL"},
            "scheduler": {"MYKHAYA_DATABASE_URL"},
            "migrate": {"MYKHAYA_DATABASE_URL"},
            "test": {"MYKHAYA_DATABASE_URL"},
            "worker": {"MYKHAYA_DATABASE_URL"} | contract.APNS,
            "postgres": {"POSTGRES_PASSWORD", "MYKHAYA_MIGRATION_DB_PASSWORD", "MYKHAYA_DB_PASSWORD"},
        }
        # Names delivered by each service's files in the two models.
        legacy_file_names = {n: dotenv_names for n in ("api", "worker", "scheduler", "migrate", "test")}
        split_file_names = {
            service: set().union(*(contract.parse_env_file(self.cfg.root / f)[0]
                                   for f in files))
            for service, files in contract.SERVICE_ENV_FILES.items()
        }
        split_file_names["test"] = set(contract.parse_env_file(ROOT / ".env.dev.test.example")[0])
        for name in legacy["services"]:
            legacy_env = legacy["services"][name].get("environment") or {}
            split_env = split["services"][name].get("environment") or {}
            expected = {k: v for k, v in legacy_env.items()
                        if k not in removed.get(name, set()) | legacy_file_names.get(name, set())}
            declared = {k: v for k, v in split_env.items()
                        if k not in split_file_names.get(name, set()) or k in expected}
            self.assertEqual(declared, expected, name)
            if name in contract.RESTATED_ENVIRONMENT:
                self.assertEqual(set(declared), set(contract.RESTATED_ENVIRONMENT[name]), name)
        # Every removed legacy value carried an interpolated secret or worker APNs value.
        for name, keys in removed.items():
            env = legacy["services"][name]["environment"]
            for key in keys & {"MYKHAYA_DATABASE_URL", "POSTGRES_PASSWORD",
                               "MYKHAYA_MIGRATION_DB_PASSWORD", "MYKHAYA_DB_PASSWORD"}:
                self.assertTrue(any(secret in env[key] for secret in SECRETS), f"{name}.{key}")

    def test_only_worker_and_scheduler_mounts_are_narrowed(self):
        legacy, split, _ = self.paired_models()
        legacy, split = legacy["services"], split["services"]
        for name in legacy:
            if name in {"worker", "scheduler"}:
                continue
            self.assertEqual(split[name].get("volumes"), legacy[name].get("volumes"), name)
        targets = {n: {m["target"] for m in split[n]["volumes"]} for n in ("worker", "scheduler")}
        self.assertEqual(targets, {k: contract.EXPECTED_MOUNTS[k] for k in targets})
        self.assertNotIn("/run/secrets/mykhaya-apple", targets["worker"] | targets["scheduler"])

    def test_production_model_never_loads_the_dev_overlay(self):
        production = (ROOT / "compose.production.yml").read_text(encoding="utf-8")
        self.assertNotIn("service-env", production)
        self.assertNotIn("MYKHAYA_DEV_CONFIG_ROOT", (ROOT / "compose.yml").read_text(encoding="utf-8"))
        # PROD has its own service-env overlay (F-03); it must never load DEV's.
        for name in ("prod-deploy.sh", "prod-config-mode.sh", "prod-health.sh"):
            prod_script = (ROOT / "infrastructure/scripts" / name).read_text(encoding="utf-8")
            self.assertNotIn("compose.dev.service-env.yml", prod_script)
            self.assertNotIn("compose.dev.yml", prod_script)
            self.assertNotIn("MYKHAYA_DEV_CONFIG_ROOT", prod_script)


class DotenvFallbackRegressionTests(unittest.TestCase):
    """Pydantic's env_file=".env" must never find a file in any image."""

    def test_build_context_excludes_dotenv_files(self):
        ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
        self.assertIn(".env", ignored)
        self.assertIn(".env.*", ignored)
        self.assertIn("secrets/", ignored)

    def test_api_image_copies_only_named_paths(self):
        dockerfile = (ROOT / "apps/api/Dockerfile").read_text(encoding="utf-8")
        for line in dockerfile.splitlines():
            if line.startswith("COPY") and "--from=" not in line:
                sources = line.split()[1:-1]
                sources = [s for s in sources if not s.startswith("--")]
                self.assertNotIn(".", sources, line)
                self.assertFalse(any(Path(s).name.startswith(".env") for s in sources), line)

    def test_no_compose_file_mounts_dotenv_or_the_repository_into_the_app(self):
        for path in ROOT.glob("compose*.yml"):
            text = path.read_text(encoding="utf-8")
            self.assertNotRegex(text, r"\.env[\"']?\s*:\s*/", path.name)
            self.assertNotRegex(text, r"[\"'\s\[](\./?|\.\.)\s*:\s*/(app|build)\b", path.name)

    def test_settings_dotenv_fallback_is_still_declared_and_tracked(self):
        # Documented compatibility finding: removing it is a separate, approved change.
        config = (ROOT / "apps/api/mykhaya/config.py").read_text(encoding="utf-8")
        self.assertEqual(len(re.findall(r'env_file="\.env"', config)), 1)


def contract_safe(text: str) -> str:
    for secret in SECRETS:
        text = text.replace(secret, "<redacted>")
    return text[:2000]


if __name__ == "__main__":
    unittest.main()
