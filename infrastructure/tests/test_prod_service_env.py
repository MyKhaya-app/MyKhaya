"""PROD service-specific configuration: contract, merged model and safety (F-03).

Synthetic values only. The Compose model is resolved by the real Docker CLI
(no daemon needed) in a throwaway project directory, never the repository's
own .env, and is held in memory; tests report names, never values.
"""

from __future__ import annotations

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
sys.path.insert(0, str(ROOT / "infrastructure" / "scripts"))
import prod_service_env_migration as migration
import service_env_contract as contract
import synthetic_prod_config as synthetic

PROD = contract.PROD
OVERLAY = ROOT / "compose.production.service-env.yml"
SCRIPTS = ROOT / "infrastructure" / "scripts"
# Assembled at runtime so secret scanners do not mistake it for a credential.
TEST_MODE_STRIPE = "sk_" + "test_" + "synthetic"


def docker_compose_available() -> bool:
    if not shutil.which("docker"):
        return False
    return subprocess.run(["docker", "compose", "version"], capture_output=True,
                          check=False).returncode == 0


def safe(text: str) -> str:
    for secret in synthetic.SECRET_VALUES:
        text = text.replace(secret, "<synthetic secret>")
    return text[-1500:]


class SyntheticProd:
    def __init__(self, *, extra: str = "") -> None:
        self.base = Path(tempfile.mkdtemp(prefix="mykhaya-prod-contract-"))
        self.env, self.root, self.field_keys, self.apple = synthetic.write_layout(self.base)
        if extra:
            with self.env.open("a", encoding="utf-8") as handle:
                handle.write(extra)
        self.legacy, problems = contract.parse_env_file(self.env)
        assert not problems, problems
        self.files, self.report = contract.split_legacy_env(self.legacy, PROD)
        contract.write_split(self.files, self.root, PROD)

    def validate(self) -> contract.Report:
        return contract.validate_root(self.root, repo_root=ROOT, check_perms=False, profile=PROD)

    def rewrite(self, name: str, values: dict[str, str]) -> None:
        (self.root / name).write_text("".join(f"{k}={contract.format_env_value(v)}\n"
                                              for k, v in values.items()), encoding="utf-8")

    def cleanup(self) -> None:
        shutil.rmtree(self.base, ignore_errors=True)


class ProdContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cfg = SyntheticProd()
        self.addCleanup(self.cfg.cleanup)

    def errors_after(self, name: str, **changes: str | None) -> list[str]:
        values = dict(self.cfg.files[name])
        for key, value in changes.items():
            if value is None:
                values.pop(key, None)
            else:
                values[key] = value
        self.cfg.rewrite(name, values)
        return self.cfg.validate().errors

    def test_split_of_the_legacy_production_env_passes(self):
        report = self.cfg.validate()
        self.assertEqual(report.errors, [])

    def test_split_classifies_every_legacy_name(self):
        report = self.cfg.report
        self.assertEqual(report[contract.UNCLASSIFIED_HEADING], [])
        self.assertEqual(report[contract.HOST_ONLY_HEADING], ["MYKHAYA_PRODUCTION"])
        self.assertEqual(report["pinned (no effect today; dropped)"],
                         ["MYKHAYA_ADMIN_MFA_REQUIRED", "MYKHAYA_COOKIE_SECURE",
                          "MYKHAYA_ENVIRONMENT"])

    def test_credentials_reach_only_their_consumers(self):
        files = self.cfg.files
        bootstrap = {"MYKHAYA_POSTGRES_ADMIN_PASSWORD", "MYKHAYA_MIGRATION_DB_PASSWORD",
                     "MYKHAYA_DB_PASSWORD", "POSTGRES_PASSWORD"}
        self.assertEqual(set(files["postgres.env"]), bootstrap - {"POSTGRES_PASSWORD"})
        for name in ("api.env", "worker.env", "scheduler.env", "migrate.env", "common.env",
                     "compose.env"):
            self.assertFalse(set(files[name]) & bootstrap, name)
            self.assertFalse(set(files[name]) & contract.FIELD_KEY_ENV_FALLBACK, name)
        self.assertEqual(set(files["migrate.env"]), {"MYKHAYA_DATABASE_URL", "MYKHAYA_SECRET_KEY"})
        self.assertIn("mykhaya_migrator", files["migrate.env"]["MYKHAYA_DATABASE_URL"])
        for secret in ("MYKHAYA_STRIPE_SECRET_KEY", "MYKHAYA_GOOGLE_CLIENT_SECRET",
                       "MYKHAYA_DVSA_CLIENT_SECRET", "MYKHAYA_DVLA_PRODUCTION_API_KEY"):
            self.assertNotIn(secret, files["worker.env"])
        self.assertFalse(set(files["api.env"]) & contract.APNS)
        self.assertIn("MYKHAYA_APNS_PRIVATE_KEY", files["worker.env"])
        # The non-secret files hold no credential (web reads only the boolean
        # MYKHAYA_EMAIL_DELIVERY_CONFIGURED from compose.env).
        credentials = contract.CORE | contract.SMTP | contract.STRIPE
        credentials -= {"MYKHAYA_EMAIL_DELIVERY_CONFIGURED"}
        for name in ("common.env", "compose.env"):
            self.assertFalse(set(files[name]) & credentials, name)
        # The installation values production Settings require reach every
        # backend service, migrate included, through common.env.
        self.assertTrue(contract.INSTALLATION_REQUIRED <= set(files["common.env"]))
        self.assertEqual(PROD.service_env_files["migrate"], ("common.env", "migrate.env"))
        self.assertEqual(files["compose.env"]["WEB_DOMAIN"], "synthetic.example.invalid")

    def test_worker_keeps_the_legacy_interpolated_defaults(self):
        cfg = SyntheticProd(extra="")
        self.addCleanup(cfg.cleanup)
        legacy = {k: v for k, v in cfg.legacy.items()
                  if not k.startswith(("MYKHAYA_APNS_", "MYKHAYA_FCM_"))}
        files, _ = contract.split_legacy_env(legacy, PROD)
        worker = files["worker.env"]
        self.assertEqual(worker["MYKHAYA_APNS_BUNDLE_ID"], "app.mykhaya.mobile")
        self.assertEqual(worker["MYKHAYA_FCM_DELIVERY_CONFIGURED"], "false")
        self.assertEqual(worker["MYKHAYA_APNS_PRIVATE_KEY"], "")
        report = contract.Report()
        contract.check_production_separation({"worker.env": worker}, report)
        self.assertEqual(report.errors, [])
        self.assertTrue(any("Compose default" in w for w in report.warnings))
        worker["MYKHAYA_APNS_DELIVERY_CONFIGURED"] = "true"
        report = contract.Report()
        contract.check_production_separation({"worker.env": worker}, report)
        self.assertTrue(any("DEV iOS app while APNs" in e for e in report.errors))

    def test_dev_identities_are_rejected(self):
        cases = (
            ("api.env", {"MYKHAYA_STRIPE_SECRET_KEY": TEST_MODE_STRIPE}, "test-mode key"),
            ("worker.env", {"MYKHAYA_FCM_PROJECT_ID": "mykhaya-dev-faf55"}, "DEV Firebase"),
            ("common.env", {"MYKHAYA_PUBLIC_WEB_URL": "https://dev.mykhaya.app"}, "DEV host name"),
            ("api.env", {"MYKHAYA_NATIVE_APPLE_RETURN_URI": "app.mykhaya.mobile://auth/callback"},
             "native return scheme"),
            ("compose.env", {"MYKHAYA_FIELD_KEYS_HOST_DIR": "/etc/mykhaya/dev/field-keys"},
             "development path"),
        )
        for name, change, fragment in cases:
            with self.subTest(fragment):
                errors = self.errors_after(name, **change)
                self.assertTrue(any(fragment in e for e in errors), errors)
                self.cfg.rewrite(name, self.cfg.files[name])

    def test_contract_rejections_mirror_dev(self):
        pinned = {"MYKHAYA_ENVIRONMENT": "production"}
        self.assertTrue(any("pinned by compose.production.yml" in e for e in
                            self.errors_after("api.env", **pinned)))
        self.cfg.rewrite("api.env", self.cfg.files["api.env"])
        self.assertTrue(any("must not be supplied" in e for e in
                            self.errors_after("worker.env", MYKHAYA_STRIPE_SECRET_KEY="x")))
        self.cfg.rewrite("worker.env", self.cfg.files["worker.env"])
        self.assertTrue(any("must not be supplied" in e for e in
                            self.errors_after("api.env", MYKHAYA_FIELD_ENCRYPTION_KEYS="x")))
        self.cfg.rewrite("api.env", self.cfg.files["api.env"])
        self.assertTrue(any("required variable MYKHAYA_ADMIN_ALLOWED_NETWORKS" in e for e in
                            self.errors_after("common.env", MYKHAYA_ADMIN_ALLOWED_NETWORKS=None)))
        self.cfg.rewrite("common.env", self.cfg.files["common.env"])
        self.assertTrue(any("does not match MYKHAYA_DB_PASSWORD" in e for e in
                            self.errors_after("postgres.env", MYKHAYA_DB_PASSWORD="other")))
        self.cfg.rewrite("postgres.env", self.cfg.files["postgres.env"])
        self.assertTrue(any("must differ" in e for e in self.errors_after(
            "postgres.env", MYKHAYA_POSTGRES_ADMIN_PASSWORD=synthetic.RUNTIME_PASSWORD)))
        self.cfg.rewrite("postgres.env", self.cfg.files["postgres.env"])
        self.assertTrue(any("never" not in e and "BACKUP_AGE_IDENTITY" in e for e in
                            self.errors_after("compose.env", MYKHAYA_BACKUP_AGE_IDENTITY="/x")))

    def test_root_location_rules_are_mirrored(self):
        report = contract.Report()
        contract.check_root_location(Path("/etc/mykhaya/dev"), ROOT, report, PROD)
        self.assertTrue(any("development path" in e for e in report.errors))
        report = contract.Report()
        contract.check_root_location(ROOT / "infrastructure", ROOT, report, PROD)
        self.assertTrue(any("inside the repository" in e for e in report.errors))
        report = contract.Report()
        contract.check_root_location(Path("/etc/mykhaya/prod"), ROOT, report)  # DEV default
        self.assertTrue(any("production path; DEV must use its own root" in e for e in report.errors))

    def test_dev_profile_is_unchanged(self):
        legacy = {"MYKHAYA_POSTGRES_ADMIN_PASSWORD": "a", "MYKHAYA_DB_PASSWORD": "b",
                  "MYKHAYA_PUBLIC_WEB_URL": "https://dev.mykhaya.app"}
        files, report = contract.split_legacy_env(legacy)
        self.assertEqual(files["postgres.env"], {"POSTGRES_PASSWORD": "a", "MYKHAYA_DB_PASSWORD": "b"})
        self.assertNotIn(contract.HOST_ONLY_HEADING, report)
        self.assertEqual(report["pinned (no effect today; dropped)"], ["MYKHAYA_PUBLIC_WEB_URL"])
        self.assertIs(contract.DEV.contracts, contract.CONTRACTS)
        self.assertFalse(contract.DEV.allow_unprovisioned_keys)
        self.assertEqual(contract.DEV.worker_interpolated_defaults, {})


class UnprovisionedKeyDirectoryTests(unittest.TestCase):
    """PROD may run with sensitive-field keyrings not yet provisioned (Phase 2B
    gate). An empty directory that nothing reads is a warning, never a pass
    for anything that holds or needs keys."""

    def setUp(self) -> None:
        self.directory = Path(tempfile.mkdtemp(prefix="mykhaya-keys-"))
        self.addCleanup(shutil.rmtree, self.directory, True)

    def probe(self, *, uid=0, gid=0, mode=0o755, entries=()):
        inode = self.directory.lstat().st_ino

        def run(_source: str) -> contract.KeyDirListing:
            root = contract.KeyEntry(".", "directory", mode, uid, gid, inode, True)
            return contract.KeyDirListing(10001, 10001, (10001,), root, tuple(entries))
        return run

    def check(self, probe, *, allow=True, referenced=frozenset()) -> contract.Report:
        report = contract.Report()
        contract.check_key_directory(contract.P + "FIELD_KEYS_HOST_DIR", self.directory, probe,
                                     report, set(referenced), allow_unprovisioned=allow)
        return report

    def test_empty_directory_is_a_warning_in_prod(self):
        report = self.check(self.probe())
        self.assertEqual(report.errors, [])
        self.assertTrue(any("not provisioned" in w for w in report.warnings))

    def test_empty_directory_still_fails_in_dev_or_when_keys_are_needed(self):
        self.assertTrue(any("is empty" in e for e in self.check(self.probe(), allow=False).errors))
        self.assertTrue(self.check(self.probe(), referenced={"field-encryption-keys.json"}).errors)
        files = {"common.env": {"MYKHAYA_SENSITIVE_FIELD_KEYS_REQUIRED": "true"}}
        self.assertEqual(contract._required_key_dirs(files), {"MYKHAYA_FIELD_KEYS_HOST_DIR"})

    def test_ownership_and_write_access_are_still_enforced(self):
        uid = os.geteuid() if hasattr(os, "geteuid") else None
        if uid not in (None, 0):
            self.assertTrue(self.check(self.probe(uid=uid)).errors)
        self.assertTrue(self.check(self.probe(uid=4242)).errors)
        self.assertTrue(self.check(self.probe(gid=4242)).errors)
        self.assertTrue(self.check(self.probe(mode=0o777)).errors)

    def test_probe_metadata_is_optional_and_validated(self):
        listing = contract.parse_probe_output(json.dumps({
            "uid": 10001, "gid": 10001, "groups": [],
            "root": {"name": ".", "kind": "directory", "mode": 0o750, "uid": 0, "gid": 10001,
                     "inode": 1, "readable": True, "size": 4096, "mtime_ns": 5},
            "entries": []}))
        self.assertEqual((listing.root.size, listing.root.mtime_ns), (4096, 5))
        with self.assertRaises(contract.ProbeFailure):
            contract.parse_probe_output(json.dumps({
                "uid": 10001, "gid": 10001, "groups": [],
                "root": {"name": ".", "kind": "directory", "mode": 0o750, "uid": 0, "gid": 10001,
                         "inode": 1, "readable": True, "size": -1}, "entries": []}))


@unittest.skipUnless(docker_compose_available(), "Docker Compose CLI required")
class ProdComposeModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cfg = SyntheticProd()
        cls.project = cls.cfg.base / "project"
        cls.project.mkdir()
        shutil.copy(cls.cfg.env, cls.project / ".env")
        shutil.copy(ROOT / ".env.dev.test.example", cls.project / ".env.dev.test.example")
        cls.base_env = {k: v for k, v in os.environ.items()
                        if not k.startswith(("MYKHAYA_", "COMPOSE_"))}
        cls.base_env["MSYS_NO_PATHCONV"] = "1"
        cls.files = ["-f", str(ROOT / "compose.yml"), "-f", str(ROOT / "compose.production.yml")]

    @classmethod
    def tearDownClass(cls) -> None:
        cls.cfg.cleanup()

    def compose(self, *args: str, service_env: bool, root: Path | None = None,
                extra_files: tuple[str, ...] = ()) -> subprocess.CompletedProcess:
        root = root or self.cfg.root
        env = dict(self.base_env)
        command = ["docker", "compose", "--project-directory", str(self.project)]
        if service_env:
            env.update({"MYKHAYA_PROD_CONFIG_ROOT": str(root), "MYKHAYA_APNS_PRIVATE_KEY": "",
                        "MYKHAYA_FCM_PRIVATE_KEY": ""})
            command += ["--env-file", str(root / "compose.env"), "--env-file",
                        str(root / "postgres.env"), *self.files, "-f", str(OVERLAY)]
        else:
            command += self.files
        for extra in extra_files:
            command += ["-f", extra]
        return subprocess.run([*command, *args], capture_output=True, text=True, env=env,
                              check=False)

    def model(self, *, service_env: bool, **kwargs) -> dict:
        result = self.compose("--profile", "tools", "config", "--format", "json",
                              service_env=service_env, **kwargs)
        self.assertEqual(result.returncode, 0, safe(result.stderr))
        return json.loads(result.stdout)

    def test_merged_model_matches_contract_and_provenance(self):
        model = self.model(service_env=True)
        self.assertEqual(contract.check_resolved_model(model, ROOT, PROD), [])
        self.assertEqual(contract.check_provenance(model, self.cfg.root, PROD), [])

    def test_every_retained_value_equals_the_legacy_model(self):
        legacy, new = self.model(service_env=False), self.model(service_env=True)
        for service in ("api", "worker", "scheduler", "migrate", "postgres", "redis", "web", "caddy"):
            old_env = migration.model_env(legacy, service)
            for name, value in migration.model_env(new, service).items():
                self.assertIn(name, old_env, f"{service}.{name}")
                self.assertEqual(value, old_env[name], f"{service}.{name}")
        # And what each application service loses is exactly what the contract removes.
        lost = set(migration.model_env(legacy, "api")) - set(migration.model_env(new, "api"))
        self.assertTrue({"MYKHAYA_DB_PASSWORD", "MYKHAYA_POSTGRES_ADMIN_PASSWORD",
                         "MYKHAYA_PRODUCTION", "WEB_DOMAIN"} <= lost)

    def test_data_web_and_proxy_services_keep_their_hash_across_modes(self):
        for service in ("postgres", "redis", "web", "caddy"):
            old = self.compose("config", f"--hash={service}", service_env=False)
            new = self.compose("config", f"--hash={service}", service_env=True)
            self.assertEqual(old.stdout, new.stdout, service)
        for service in ("api", "worker", "scheduler"):
            old = self.compose("config", f"--hash={service}", service_env=False)
            new = self.compose("config", f"--hash={service}", service_env=True)
            self.assertNotEqual(old.stdout, new.stdout, service)

    def test_hardening_and_runtime_behaviour_match_legacy(self):
        legacy, new = self.model(service_env=False)["services"], self.model(service_env=True)["services"]
        self.assertEqual(set(legacy), set(new))
        keys = ("read_only", "cap_drop", "cap_add", "security_opt", "tmpfs", "restart", "logging",
                "healthcheck", "networks", "stop_grace_period", "user", "command", "depends_on",
                "ports", "profiles", "build", "image")
        for name in legacy:
            for key in keys:
                self.assertEqual(new[name].get(key), legacy[name].get(key), f"{name}.{key}")
        for name in legacy:
            if name not in {"worker", "scheduler"}:
                self.assertEqual(new[name].get("volumes"), legacy[name].get("volumes"), name)
        self.assertEqual(self.model(service_env=True)["volumes"]["home_migration_data"]["name"],
                         "mykhaya_prod_home_migration_data")

    def test_provenance_detects_any_extra_source_and_password_leaks(self):
        extra = self.cfg.base / "extra.yml"
        extra.write_text(
            "services:\n  worker:\n    environment:\n      MYKHAYA_STRIPE_SECRET_KEY: leaked\n"
            "  web:\n    environment:\n      MYKHAYA_SYNTHETIC: \"x${MYKHAYA_DB_PASSWORD}\"\n",
            encoding="utf-8")
        model = self.model(service_env=True, extra_files=(str(extra),))
        errors = contract.check_provenance(model, self.cfg.root, PROD)
        self.assertIn("worker: receives MYKHAYA_STRIPE_SECRET_KEY from outside "
                      "MYKHAYA_PROD_CONFIG_ROOT", errors)
        self.assertIn("web: MYKHAYA_SYNTHETIC contains the PostgreSQL runtime password", errors)
        self.assertTrue(all(s not in e for e in errors for s in synthetic.SECRET_VALUES))

    def test_missing_root_variable_or_file_fails_closed(self):
        env = dict(self.base_env)
        result = subprocess.run(
            ["docker", "compose", "--project-directory", str(self.project), "--env-file",
             str(self.cfg.root / "compose.env"), *self.files, "-f", str(OVERLAY), "config",
             "--quiet"], capture_output=True, text=True, env=env, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("MYKHAYA_PROD_CONFIG_ROOT", result.stderr)
        cfg = SyntheticProd()
        self.addCleanup(cfg.cleanup)
        (cfg.root / "scheduler.env").unlink()
        result = self.compose("config", "--quiet", service_env=True, root=cfg.root)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("scheduler.env", result.stderr)

    def test_legacy_production_model_does_not_know_the_overlay(self):
        for name in ("compose.yml", "compose.production.yml"):
            text = (ROOT / name).read_text(encoding="utf-8")
            self.assertNotIn("service-env", text)
            self.assertNotIn("MYKHAYA_PROD_CONFIG_ROOT", text)


class ProdScriptSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.texts = {p.name: p.read_text(encoding="utf-8") for p in (
            SCRIPTS / "prod-deploy.sh", SCRIPTS / "prod-config-mode.sh", SCRIPTS / "prod-health.sh",
            SCRIPTS / "prod-logs.sh", SCRIPTS / "prod-install.sh", SCRIPTS / "cutover-state.sh",
            SCRIPTS / "prod-service-env-migrate.sh", SCRIPTS / "prod_service_env_migration.py",
            SCRIPTS / "backup-config-mode.sh", OVERLAY)}

    def test_nothing_deletes_volumes_prunes_or_downgrades(self):
        for name, text in self.texts.items():
            self.assertNotRegex(text, r"\bdown\b\s+-v|--volumes|\bvolume\s+rm\b|\bprune\b", name)
            self.assertNotRegex(text, r"alembic\s+downgrade", name)
            self.assertNotRegex(text, r"compose[^\n]*\bdown\b", name)

    def test_migration_queries_are_read_only(self):
        module = self.texts["prod_service_env_migration.py"]
        queries = re.findall(r'psql\(pg, f?"([^"]+)', module)
        self.assertGreaterEqual(len(queries), 3)
        for query in queries:
            self.assertTrue(query.lower().startswith("select"), query)
        # Every database call goes through psql(pg, ...): one definition plus the queries.
        self.assertEqual(module.count("psql("), len(queries) + 1)

    def test_configuration_only_deployments_never_rebuild(self):
        deploy = self.texts["prod-deploy.sh"]
        self.assertIn('[ "${MYKHAYA_PROD_REUSE_IMAGES:-0}" = 1 ] || prod_compose build', deploy)
        reuse = deploy[deploy.index("reuse_release_images() {"):deploy.index("begin_transition() {")]
        self.assertNotRegex(reuse, r"docker pull|--pull\b|compose[^\n]*\bpull\b")
        self.assertNotIn("compose build", reuse)
        self.assertIn('"MYKHAYA_PROD_REUSE_IMAGES": "1"', self.texts["prod_service_env_migration.py"])

    def test_cutover_becomes_active_only_through_verification(self):
        deploy = self.texts["prod-deploy.sh"]
        complete = deploy[deploy.index("complete_transition() {"):deploy.index("update() {")]
        self.assertNotIn("cutover_write_state \"$PROD_STATE_FILE\" active", complete)
        module = self.texts["prod_service_env_migration.py"]
        verify = module.index("m.verify_cutover(snapshot)")
        self.assertLess(verify, module.index('m.write_state("active")'))

    def test_update_reexecutes_the_release_copy_after_checkout(self):
        deploy = self.texts["prod-deploy.sh"]
        update = deploy[deploy.index("\nupdate() {"):deploy.index("continue_update() {")]
        self.assertLess(update.index("git checkout --detach"), update.index("exec sh"))
        self.assertIn("continue-update", update[update.index("exec sh"):])
        continued = deploy[deploy.index("continue_update() {"):]
        self.assertIn("verify_tag_checkout", continued[:continued.index("\n}\n")])

    def test_compose_invocation_is_identical_everywhere(self):
        mode = self.texts["prod-config-mode.sh"]
        self.assertIn('--env-file "$PROD_CONFIG_ROOT/compose.env" --env-file '
                      '"$PROD_CONFIG_ROOT/postgres.env"', mode)
        self.assertIn('-f "$ROOT/compose.yml" -f "$ROOT/compose.production.yml" -f '
                      '"$ROOT/$PROD_OVERLAY"', mode)
        self.assertIn("unset MYKHAYA_DB_PASSWORD MYKHAYA_MIGRATION_DB_PASSWORD "
                      "MYKHAYA_POSTGRES_ADMIN_PASSWORD", mode)
        paths = migration.Paths(ROOT, Path("/etc/mykhaya/prod/.service-env-state"), Path("/m"),
                                Path("/r"), Path("/c"), Path("/d"))
        command, env = migration.compose_command(paths, "service-env")
        root = Path("/etc/mykhaya/prod")
        self.assertEqual(command[2:6], ["--env-file", str(root / "compose.env"),
                                        "--env-file", str(root / "postgres.env")])
        self.assertTrue(command[-1].endswith("compose.production.service-env.yml"))
        self.assertNotIn("MYKHAYA_DB_PASSWORD", env)
        self.assertEqual(env["MYKHAYA_FCM_PRIVATE_KEY"], "")
        legacy, _ = migration.compose_command(paths, "legacy")
        self.assertNotIn("--env-file", legacy)

    def test_validator_uses_the_same_prod_command(self):
        import validate_backend_config as validator
        saved = dict(os.environ)
        try:
            os.environ.update({"MYKHAYA_PRODUCTION": "1",
                               "MYKHAYA_PROD_CONFIG_ROOT": "/etc/mykhaya/prod"})
            os.environ["MYKHAYA_DB_PASSWORD"] = "from-shell"
            args = validator.base_compose_args()
            self.assertEqual(args[2:6], ["--env-file", "/etc/mykhaya/prod/compose.env",
                                         "--env-file", "/etc/mykhaya/prod/postgres.env"])
            self.assertEqual(args[-1], "compose.production.service-env.yml")
            env = validator.compose_environment()
            self.assertNotIn("MYKHAYA_DB_PASSWORD", env)
            self.assertEqual(env["MYKHAYA_APNS_PRIVATE_KEY"], "")
            os.environ.pop("MYKHAYA_PROD_CONFIG_ROOT")
            self.assertEqual(validator.base_compose_args(), list(validator.COMPOSE_FILES))
        finally:
            os.environ.clear()
            os.environ.update(saved)

    def test_legacy_production_commands_are_unchanged(self):
        mode = self.texts["prod-config-mode.sh"]
        self.assertIn("    docker compose -f compose.yml -f compose.production.yml \"$@\"", mode)
        install = self.texts["prod-install.sh"]
        for line in ("docker compose -f compose.yml -f compose.production.yml up -d postgres redis",
                     "docker compose -f compose.yml -f compose.production.yml run --rm --no-deps migrate"):
            self.assertIn(line, install)
        for name in ("backup.sh", "restore.sh"):
            text = (SCRIPTS / name).read_text(encoding="utf-8")
            self.assertIn("backup-config-mode.sh", text)
            self.assertNotIn("docker compose exec", text)
        self.assertIn('stack_compose() { docker compose "$@"; }', self.texts["backup-config-mode.sh"])

    @unittest.skipUnless(shutil.which("sh"), "POSIX sh required")
    def test_host_guard_refuses_local_targets_on_the_prod_host(self):
        base = Path(tempfile.mkdtemp(prefix="mykhaya-guard-"))
        self.addCleanup(shutil.rmtree, base, True)
        env = {k: v for k, v in os.environ.items() if not k.startswith("MYKHAYA_")}
        env.update({"MYKHAYA_DEV_SERVICE_ENV_STATE": (base / "dev" / "s").as_posix(),
                    "MYKHAYA_PROD_SERVICE_ENV_STATE": (base / "prod" / ".service-env-state").as_posix()})
        guard = str(SCRIPTS / "dev-host-guard.sh")
        self.assertEqual(subprocess.run(["sh", guard, "reset"], env=env, check=False).returncode, 0)
        (base / "prod").mkdir()
        result = subprocess.run(["sh", guard, "reset"], env=env, capture_output=True, text=True,
                                check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("refused on the PROD host", result.stderr)


class MigrationHelperTests(unittest.TestCase):
    def test_the_release_has_exactly_one_alembic_head(self):
        heads = migration.alembic_heads(ROOT / "apps" / "api" / "migrations" / "versions")
        self.assertEqual(len(heads), 1, heads)

    def test_alembic_heads_handle_merges_and_annotations(self):
        directory = Path(tempfile.mkdtemp(prefix="mykhaya-alembic-"))
        self.addCleanup(shutil.rmtree, directory, True)
        (directory / "a.py").write_text('revision: str = "a"\ndown_revision = None\n')
        (directory / "b.py").write_text('revision = "b"\ndown_revision = "a"\n')
        (directory / "c.py").write_text('revision = "c"\ndown_revision = "a"\n')
        self.assertEqual(migration.alembic_heads(directory), {"b", "c"})
        (directory / "d.py").write_text(
            'revision = "d"\ndown_revision: str | tuple[str, ...] | None = ("b", "c")\n')
        self.assertEqual(migration.alembic_heads(directory), {"d"})

    def test_small_parsers(self):
        self.assertTrue(migration.compose_version_ok("2.24.4"))
        self.assertTrue(migration.compose_version_ok("v5.1.4-desktop.1"))
        self.assertFalse(migration.compose_version_ok("2.24.3"))
        self.assertFalse(migration.compose_version_ok("garbage"))
        self.assertIsNotNone(migration.parse_timestamp("2026-11-20T10:00:00Z"))
        self.assertIsNone(migration.parse_timestamp("yesterday"))
        self.assertTrue(migration.safe_file_name("mykhaya-config-x.tar.age"))
        for name in ("", "..", "../x", "a/b", "x\n"):
            self.assertFalse(migration.safe_file_name(name), name)
        self.assertEqual(migration.MAX_BACKUP_AGE.total_seconds(), 7200)

    def test_model_mounts_resolve_named_volumes(self):
        model = {"name": "mykhaya", "volumes": {"home_migration_data": {
            "name": "mykhaya_prod_home_migration_data"}, "avatar_data": {}},
            "services": {"api": {"volumes": [
                {"type": "volume", "source": "home_migration_data", "target": "/data/home-migrations"},
                {"type": "volume", "source": "avatar_data", "target": "/data/avatars"},
                {"type": "bind", "source": "/etc/mykhaya/field-keys", "target": "/run/secrets/mykhaya"}]}}}
        self.assertEqual(migration.model_mounts(model, "api"), {
            "/data/home-migrations": "mykhaya_prod_home_migration_data",
            "/data/avatars": "mykhaya_avatar_data",
            "/run/secrets/mykhaya": "/etc/mykhaya/field-keys"})


if __name__ == "__main__":
    unittest.main()
