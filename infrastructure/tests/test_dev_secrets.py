"""DEV Docker Secrets: contract, conversion, overlay and tooling guards.

The end-to-end migration and rollback run in check-dev-secrets-migration.sh.
Every value here is synthetic.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "infrastructure" / "scripts"))
import service_env_contract as contract  # noqa: E402
import synthetic_dev_config as synthetic  # noqa: E402

P = contract.P
PEM = "-----BEGIN PRIVATE KEY-----\n" + "QUJD" * 16 + "\n-----END PRIVATE KEY-----"
OVERLAY = ROOT / "compose.dev.secrets.yml"


def load_roles():
    spec = importlib.util.spec_from_file_location(
        "process_roles_for_test", ROOT / "apps/api/mykhaya/process_roles.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ROLES = load_roles()


def f03_files(**extra: dict[str, str]) -> dict[str, dict[str, str]]:
    parsed = {name: contract.parse_env_text(text, name)[0] for name, text in
              synthetic.files(Path("/srv/keys/field"), Path("/srv/keys/apple")).items()}
    for name, values in extra.items():
        parsed[f"{name}.env"].update(values)
    return parsed


def full() -> dict[str, dict[str, str]]:
    stripe = {P + "STRIPE_BILLING_CONFIGURED": "true", P + "STRIPE_SECRET_KEY": "sk_" + "test_x1",
              P + "STRIPE_WEBHOOK_SECRET": "whsec_x1"}
    dvsa = {P + "DVSA_ENABLED": "true", P + "DVSA_TOKEN_URL": "https://login.example.invalid",
            P + "DVSA_CLIENT_ID": "id-x1", P + "DVSA_CLIENT_SECRET": "se-x1", P + "DVSA_API_KEY": "ap-x1"}
    dvla = {P + "DVLA_ENVIRONMENT": "uat", P + "DVLA_UAT_API_KEY": "dv-x1",
            P + "DVLA_UAT_ENDPOINT": "https://uat.example.invalid"}
    smtp = {P + "SMTP_PASSWORD": "sm-x1"}
    fcm = {P + "FCM_DELIVERY_CONFIGURED": "true", P + "FCM_PROJECT_ID": "mykhaya-dev-faf55",
           P + "FCM_CLIENT_EMAIL": "a@example.invalid", P + "FCM_PRIVATE_KEY": PEM.replace("\n", "\\n")}
    return f03_files(
        api={**stripe, **dvsa, **dvla, **smtp, **fcm, P + "GOOGLE_CLIENT_SECRET": "go-x1"},
        worker={**smtp, **fcm, P + "APNS_PRIVATE_KEY": PEM},
        scheduler={**stripe, **dvsa, **dvla, **smtp, P + "MONITORING_WATCHDOG_URL": "https://w.example.invalid/x"},
    )


class GrantTests(unittest.TestCase):
    def test_grants_equal_the_application_role_matrix(self) -> None:
        by_env = {name: identifier for identifier, spec in ROLES.CREDENTIALS.items()
                  for name in spec.env}
        for secret in contract.SECRET_FILE_SPECS:
            for literal in secret.literals:
                allowed = {role for role in ("api", "worker", "scheduler")
                           if by_env[literal] in ROLES.ROLE_GRANTS[role]}
                self.assertEqual(set(secret.services), allowed, secret.name)

    def test_every_file_credential_of_the_registry_has_a_secret(self) -> None:
        source = (ROOT / "apps/api/mykhaya/secret_registry.py").read_text(encoding="utf-8")
        settings = {P + name.upper() for name in re.findall(r'_spec\("([a-z_]+)"', source)}
        settings -= {P + "DATABASE_PASSWORD", *contract.FIELD_KEY_ENV_FALLBACK}
        self.assertEqual(settings, {n for s in contract.SECRET_FILE_SPECS for n in s.literals})

    def test_presence_flags_match_the_application(self) -> None:
        self.assertLessEqual(contract.SCHEDULER_PRESENCE | {contract.FCM_PRESENCE},
                             set(ROLES.PRESENCE_FLAGS))

    def test_migrate_receives_only_the_migration_credential(self) -> None:
        self.assertEqual(contract.service_secrets("migrate"), {"migration_db_password"})
        self.assertEqual(contract.SECRETS_MIGRATE.allowed,
                         {P + "DATABASE_URL", P + "DATABASE_PASSWORD_FILE"})

    def test_the_f03_and_production_profiles_are_unchanged(self) -> None:
        self.assertIn(P + "SECRET_KEY", contract.MIGRATE.required)
        for profile in (contract.DEV, contract.PROD):
            self.assertFalse(profile.file_backed)
            for item in profile.contracts:
                self.assertNotIn(contract.PROCESS_ROLE, item.allowed)
                self.assertNotIn(contract.DATABASE_PASSWORD_FILE, item.allowed)


class ConversionTests(unittest.TestCase):
    def convert(self, files):
        return contract.derive_file_backed(files)

    def test_every_value_is_moved_unchanged_and_removed_from_the_environment(self) -> None:
        out, values, problems = self.convert(full())
        self.assertEqual(problems, [])
        self.assertEqual(values["secret_key"], synthetic.SECRET_KEY)
        self.assertEqual(values["app_db_password"], synthetic.RUNTIME_PASSWORD)
        self.assertEqual(values["migration_db_password"], synthetic.MIGRATION_PASSWORD)
        self.assertEqual(values["postgres_admin_password"], synthetic.ADMIN_PASSWORD)
        self.assertEqual(values["fcm_private_key"], PEM)
        self.assertEqual(values["apns_private_key"], PEM)
        text = json.dumps(out)
        for secret, value in values.items():
            if value:
                self.assertNotIn(value.split("\n")[1] if "\n" in value else value, text, secret)

    def test_converted_files_satisfy_the_contract(self) -> None:
        for files in (full(), f03_files()):
            out, _, problems = self.convert(files)
            report = contract.Report()
            for item in contract.DEV_SECRETS.contracts:
                contract.check_contract(item, out[item.name], report, contract.DEV_SECRETS)
            contract.check_file_backed(out, report)
            self.assertEqual((problems, report.errors), ([], []))

    def test_presence_flags_state_what_monitoring_reads_today(self) -> None:
        out, _, _ = self.convert(full())
        for flag in contract.SCHEDULER_PRESENCE:
            self.assertEqual(out["scheduler.env"][flag], "true")
        self.assertEqual(out["api.env"][contract.FCM_PRESENCE], "true")
        files = full()
        for name in ("DVLA_UAT_API_KEY", "DVSA_API_KEY", "STRIPE_WEBHOOK_SECRET"):
            del files["scheduler.env"][P + name]
        out, _, _ = self.convert(files)
        for flag in contract.SCHEDULER_PRESENCE:
            self.assertEqual(out["scheduler.env"][flag], "false")

    def test_unsafe_or_inconsistent_values_are_refused_by_name(self) -> None:
        cases = (
            ("worker", P + "SMTP_PASSWORD", "other-x1", "differs between service files"),
            ("api", P + "GOOGLE_CLIENT_SECRET", " padded ", "leading or trailing whitespace"),
            ("api", P + "GOOGLE_CLIENT_SECRET", "two\nlines", "must be a single line"),
            ("worker", P + "APNS_PRIVATE_KEY", "not-pem", "not exactly one PEM block"),
            ("api", P + "FIELD_ENCRYPTION_KEYS", "{}", "install it as a key file first"),
            ("postgres", P + "DB_PASSWORD", "mismatch-x1", "differs from the password PostgreSQL"),
        )
        for service, name, value, message in cases:
            with self.subTest(name=name, value=value):
                files = full()
                files[f"{service}.env"][name] = value
                _, _, problems = self.convert(files)
                self.assertTrue(any(message in p for p in problems), problems)
                self.assertFalse(any(value.strip() and value.strip() != "{}" and value.strip() in p
                                     for p in problems))

    def test_a_percent_encoded_database_password_is_decoded(self) -> None:
        files = full()
        for service in ("api", "worker", "scheduler"):
            files[f"{service}.env"][P + "DATABASE_URL"] = \
                "postgresql+asyncpg://mykhaya_app:a%40b%2Fc@postgres:5432/mykhaya"
        files["postgres.env"][P + "DB_PASSWORD"] = "a@b/c"
        out, values, problems = self.convert(files)
        self.assertEqual((problems, values["app_db_password"]), ([], "a@b/c"))
        self.assertEqual(out["api.env"][P + "DATABASE_URL"],
                         "postgresql+asyncpg://mykhaya_app@postgres:5432/mykhaya")

    def test_stored_values_read_back_through_the_application_rules(self) -> None:
        self.assertIsNone(contract.secret_value_problem("pem", PEM))
        self.assertIsNone(contract.secret_value_problem("line", 'p@ss:w/rd "\\ é'))
        self.assertIsNotNone(contract.secret_value_problem("pem", PEM + "\n" + PEM))


class FileBackedContractTests(unittest.TestCase):
    def errors(self, mutate) -> list[str]:
        out, _, _ = contract.derive_file_backed(full())
        mutate(out)
        report = contract.Report()
        for item in contract.DEV_SECRETS.contracts:
            contract.check_contract(item, out[item.name], report, contract.DEV_SECRETS)
        contract.check_file_backed(out, report)
        return report.errors

    def assertError(self, fragment: str, mutate) -> None:
        errors = self.errors(mutate)
        self.assertTrue(any(fragment in e for e in errors), errors)

    def test_violations(self) -> None:
        def put(service, name, value):
            return lambda f: f[f"{service}.env"].__setitem__(P + name, value)
        for fragment, mutate in (
            ("MYKHAYA_SECRET_KEY must not be supplied", put("api", "SECRET_KEY", "x")),
            ("MYKHAYA_SECRET_KEY must not be supplied", put("migrate", "SECRET_KEY", "x")),
            ("must not contain a password", put("api", "DATABASE_URL",
             "postgresql+asyncpg://mykhaya_app:x@postgres:5432/mykhaya")),
            ("must use the mykhaya_migrator role", put("migrate", "DATABASE_URL",
             "postgresql+asyncpg://mykhaya_app@postgres:5432/mykhaya")),
            ("MYKHAYA_FCM_PRIVATE_KEY_FILE must not be supplied",
             put("api", "FCM_PRIVATE_KEY_FILE", "/run/secrets/fcm_private_key")),
            ("MYKHAYA_STRIPE_SECRET_KEY_FILE must not be supplied",
             put("worker", "STRIPE_SECRET_KEY_FILE", "/run/secrets/stripe_secret_key")),
            ("MYKHAYA_DVSA_API_KEY must not be supplied", put("scheduler", "DVSA_API_KEY", "x")),
            ("must be /run/secrets/smtp_password", put("api", "SMTP_PASSWORD_FILE", "/run/secrets/secret_key")),
            ("MYKHAYA_PROCESS_ROLE is pinned", put("api", "PROCESS_ROLE", "worker")),
            ("must be true or false", put("scheduler", "DVLA_API_KEY_PRESENT", "yes")),
            ("must not be supplied", put("postgres", "DB_PASSWORD", "x")),
            ("directly inside", put("common", "FIELD_ENCRYPTION_KEYS_FILE", "/run/secrets/mykhaya/../secret_key")),
            ("MYKHAYA_DVLA_API_KEY_PRESENT is required",
             lambda f: f["scheduler.env"].pop(P + "DVLA_API_KEY_PRESENT")),
            ("MYKHAYA_SECRET_KEY_FILE is missing",
             lambda f: f["worker.env"].pop(P + "SECRET_KEY_FILE")),
        ):
            with self.subTest(fragment=fragment):
                self.assertError(fragment, mutate)

    def store(self, *, mode=0o440, uid=0, gid=contract.SERVICE_GID, size=None, kind="file",
              extra=None, drop=None, readable=True) -> list[str]:
        referenced = {"secret_key", "app_db_password"}
        entries = [contract.KeyEntry(s.name, kind if s.name == "secret_key" else "file",
                                     mode if s.name == "secret_key" else 0o440, uid, gid, 1, readable,
                                     size if size is not None and s.name == "secret_key"
                                     else (10 if s.name in referenced else 0), 1)
                   for s in contract.SECRET_FILE_SPECS if s.store == "app" and s.name != drop]
        if extra:
            entries.append(contract.KeyEntry(extra, "file", 0o440, 0, gid, 1, True, 0, 1))
        listing = contract.KeyDirListing(
            contract.SERVICE_UID, contract.SERVICE_GID, (),
            contract.KeyEntry(".", "directory", 0o750, 0, contract.SERVICE_GID, 1, True), tuple(entries))
        report = contract.Report()
        contract.check_secret_store(Path("/x"), "app", referenced, lambda _: listing, report)
        return report.errors

    def test_secret_store_ownership_modes_and_contents(self) -> None:
        self.assertEqual(self.store(), [])
        for fragment, options in (
            ("mode 0444", {"mode": 0o444}), ("mode 0640", {"mode": 0o640}), ("owned by root", {"uid": 1000}),
            ("owned by root", {"gid": 0}), ("not a symlink", {"kind": "symlink"}),
            ("is empty but", {"size": 0}), ("not a recognised", {"extra": "x"}),
            ("smtp_password: is missing", {"drop": "smtp_password"}), ("not readable", {"readable": False}),
        ):
            with self.subTest(fragment=fragment):
                errors = self.store(**options)
                self.assertTrue(any(fragment in e for e in errors), errors)

    def test_an_unverifiable_store_fails_closed(self) -> None:
        report = contract.Report()
        contract.check_secret_store(Path("/x"), "postgres", set(), None, report)
        self.assertIn("cannot be verified", report.errors[0])


class MergedModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.base = tempfile.TemporaryDirectory(prefix="mykhaya-secrets-")
        base = Path(cls.base.name)
        cls.root = base / "file-backed"
        out, _, _ = contract.derive_file_backed(full())
        for store in ("app", "postgres"):
            (cls.root / "secrets" / store).mkdir(parents=True)
        for directory in ("field", "apple"):
            (base / directory).mkdir()
        out["compose.env"][P + "FIELD_KEYS_HOST_DIR"] = (base / "field").as_posix()
        out["compose.env"][P + "APPLE_KEY_HOST_DIR"] = (base / "apple").as_posix()
        for name, values in out.items():
            (cls.root / name).write_text("".join(
                f"{k}={contract.format_env_value(v)}\n" for k, v in values.items()),
                encoding="utf-8", newline="\n")
        env = {k: v for k, v in os.environ.items() if not k.startswith(("MYKHAYA_", "COMPOSE_"))}
        env["MYKHAYA_DEV_CONFIG_ROOT"] = cls.root.as_posix()
        for name in ("DB_PASSWORD", "MIGRATION_DB_PASSWORD", "POSTGRES_ADMIN_PASSWORD", "APNS_PRIVATE_KEY"):
            env[P + name] = ""
        result = subprocess.run(
            ["docker", "compose", "--env-file", (cls.root / "compose.env").as_posix(), "-f", "compose.yml",
             "-f", "compose.dev.yml", "-f", "compose.dev.service-env.yml", "-f", "compose.dev.secrets.yml",
             "config", "--format", "json"], cwd=ROOT, env=env, capture_output=True, text=True)
        if result.returncode:
            raise unittest.SkipTest("docker compose is unavailable")
        cls.model = json.loads(result.stdout)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.base.cleanup()

    def errors(self, model) -> list[str]:
        return (contract.check_resolved_model(model, ROOT, contract.DEV_SECRETS)
                + contract.check_provenance(model, self.root, contract.DEV_SECRETS)
                + contract.check_secret_mounts(model, self.root, contract.DEV_SECRETS))

    def test_the_merged_model_satisfies_the_contract(self) -> None:
        self.assertEqual(self.errors(self.model), [])

    def test_no_credential_is_in_any_environment(self) -> None:
        _, values, _ = contract.derive_file_backed(full())
        text = json.dumps({n: s.get("environment") for n, s in self.model["services"].items()
                           if n != "test"})
        for name, value in values.items():
            if len(value) > 4:
                self.assertNotIn(value.split("\n")[1] if "\n" in value else value, text, name)

    def test_tampered_models_are_refused(self) -> None:
        def change(path, value):
            model = json.loads(json.dumps(self.model))
            target = model
            for part in path[:-1]:
                target = target[part]
            target[path[-1]] = value(target[path[-1]]) if callable(value) else value
            return self.errors(model)
        for fragment, path, value in (
            ("worker: must not receive secret stripe_secret_key", ("services", "worker", "secrets"),
             lambda s: s + [{"source": "stripe_secret_key"}]),
            ("web: must not receive secret secret_key", ("services", "web"),
             lambda s: {**s, "secrets": [{"source": "secret_key"}]}),
            ("api: does not receive secret secret_key", ("services", "api", "secrets"),
             lambda s: [x for x in s if x["source"] != "secret_key"]),
            ("unexpected path", ("services", "migrate", "secrets", 0, "target"), "/etc/passwd"),
            ("does not come from", ("secrets", "secret_key", "file"), "/tmp/secret_key"),
            ("must be a plain file secret", ("secrets", "secret_key"), {"environment": "X"}),
            ("MYKHAYA_PROCESS_ROLE must be worker", ("services", "worker", "environment", contract.PROCESS_ROLE), "api"),
            ("outside its contract", ("services", "migrate", "environment"), lambda e: {**e, P + "SECRET_KEY": "x"}),
        ):
            with self.subTest(fragment=fragment):
                errors = change(path, value)
                self.assertTrue(any(fragment in e for e in errors), errors)

    def test_other_profiles_never_accept_compose_secrets(self) -> None:
        for profile in (contract.DEV, contract.PROD):
            errors = contract.check_secret_mounts(self.model, None, profile)
            self.assertTrue(any("not part of this configuration" in e for e in errors))

    def test_volumes_networks_images_and_hardening_match_f03(self) -> None:
        for name in ("api", "worker", "scheduler", "migrate", "postgres", "redis"):
            service = self.model["services"][name]
            self.assertIn("no-new-privileges:true", service["security_opt"], name)
            self.assertEqual(service["cap_drop"], ["ALL"], name)
        for name in ("api", "worker", "scheduler"):
            self.assertTrue(self.model["services"][name]["read_only"])
        self.assertEqual(self.model["volumes"]["postgres_data"]["name"], "mykhaya_postgres_data")
        self.assertEqual(self.model["name"], "mykhaya")


class RepositoryGuards(unittest.TestCase):
    def test_only_dev_tooling_references_the_secrets_overlay(self) -> None:
        for path in ROOT.glob("compose*.yml"):
            if path != OVERLAY:
                self.assertNotRegex(path.read_text(encoding="utf-8"), r"(?m)^secrets:", path.name)
        for path in (ROOT / "infrastructure/scripts").glob("prod*"):
            if path.is_file():
                self.assertNotIn("compose.dev.secrets", path.read_text(encoding="utf-8"), path.name)

    def test_the_overlay_only_adds_secrets_and_roles(self) -> None:
        text = OVERLAY.read_text(encoding="utf-8")
        for key in ("volumes:", "networks:", "ports:", "image:", "command:", "user:", "privileged:"):
            self.assertNotIn(key, text)

    def test_the_migration_never_removes_volumes_or_rotates(self) -> None:
        for name in ("dev-secrets-cutover.sh", "dev_secrets_migration.py", "dev-config-mode.sh"):
            text = (ROOT / "infrastructure/scripts" / name).read_text(encoding="utf-8")
            self.assertNotRegex(text, r"volume rm|down -v|--volumes|alembic downgrade|openssl rand|token_", name)
            self.assertNotRegex(text, r"\bssh\b|curl |wget ", name)

    def test_ci_runs_the_migration_rehearsal(self) -> None:
        workflow = (ROOT / ".github/workflows/quality.yml").read_text(encoding="utf-8")
        self.assertIn("bash infrastructure/scripts/check-dev-secrets-migration.sh", workflow)


if __name__ == "__main__":
    unittest.main()
