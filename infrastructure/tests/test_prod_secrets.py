"""PROD Docker Secrets: contract, overlay, mode selection, orchestrator guards.

The end-to-end migration, interruptions, rollback and isolated restore run in
check-prod-secrets-migration.sh. Every value here is synthetic.
"""

from __future__ import annotations

import argparse
import io
import itertools
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "infrastructure" / "scripts"
sys.path[:0] = [str(Path(__file__).resolve().parent), str(SCRIPTS)]
import prod_security_migration as orchestrator  # noqa: E402
import prod_service_env_migration as f03  # noqa: E402
import service_env_contract as contract  # noqa: E402
import synthetic_prod_config as synthetic  # noqa: E402

P = contract.P
PEM = "-----BEGIN PRIVATE KEY-----\n" + "QUJD" * 16 + "\n-----END PRIVATE KEY-----"
OVERLAY = ROOT / "compose.production.secrets.yml"
STATES = ("legacy", "pending", "active", "rollback-pending")


def f03_files() -> dict[str, dict[str, str]]:
    legacy, problems = contract.parse_env_text(
        synthetic.legacy_env(Path("/srv/keys/field"), Path("/srv/keys/apple")), ".env")
    assert not problems
    legacy.update({P + "APNS_PRIVATE_KEY": PEM, P + "FCM_PRIVATE_KEY": PEM.replace("\n", "\\n"),
                   P + "FCM_DELIVERY_CONFIGURED": "true", P + "APNS_DELIVERY_CONFIGURED": "true",
                   P + "STRIPE_BILLING_CONFIGURED": "true", P + "EMAIL_DELIVERY_CONFIGURED": "true",
                   P + "MONITORING_WATCHDOG_URL": "https://w.example.invalid/synthetic-watchdog"})
    return contract.split_legacy_env(legacy, contract.PROD)[0]


class ContractTests(unittest.TestCase):
    def test_every_prod_credential_moves_unchanged(self) -> None:
        files, values, problems = contract.derive_file_backed(f03_files(), contract.PROD)
        self.assertEqual(problems, [])
        self.assertEqual(values["postgres_admin_password"], synthetic.ADMIN_PASSWORD)
        self.assertEqual(values["migration_db_password"], synthetic.MIGRATION_PASSWORD)
        self.assertEqual(values["app_db_password"], synthetic.RUNTIME_PASSWORD)
        self.assertEqual(values["apns_private_key"], PEM)
        self.assertEqual(values["fcm_private_key"], PEM)
        text = json.dumps(files)
        for name, value in values.items():
            if value:
                self.assertNotIn(json.dumps(value)[1:-1], text, name)

    def test_converted_files_satisfy_the_prod_contract(self) -> None:
        files, _, _ = contract.derive_file_backed(f03_files(), contract.PROD)
        report = contract.Report()
        for item in contract.PROD_SECRETS.contracts:
            contract.check_contract(item, files[item.name], report, contract.PROD_SECRETS)
        contract.check_file_backed(files, report, contract.PROD_SECRETS)
        self.assertEqual(report.errors, [])
        self.assertEqual(files["scheduler.env"][P + "DVLA_API_KEY_PRESENT"], "true")
        self.assertEqual(files["scheduler.env"][P + "DVSA_CREDENTIALS_PRESENT"], "true")
        self.assertEqual(files["api.env"][contract.FCM_PRESENCE], "true")
        self.assertEqual(set(files["migrate.env"]),
                         {P + "DATABASE_URL", P + "DATABASE_PASSWORD_FILE"})

    def test_dev_identities_are_refused_and_prod_ones_accepted(self) -> None:
        files, _, _ = contract.derive_file_backed(f03_files(), contract.PROD)
        files["worker.env"][P + "FCM_PROJECT_ID"] = contract.DEVELOPMENT_FCM_PROJECT_ID
        report = contract.Report()
        contract.check_file_backed(files, report, contract.PROD_SECRETS)
        self.assertTrue(any("DEV Firebase project" in e for e in report.errors))

    def test_grants_equal_dev_and_f03_profiles_are_unchanged(self) -> None:
        self.assertEqual(contract.PROD_SECRETS.resolved_allowed["migrate"],
                         contract.DEV_SECRETS.resolved_allowed["migrate"])
        self.assertFalse(contract.PROD.file_backed)
        self.assertEqual(contract.PROD.service_env_files["migrate"], ("common.env", "migrate.env"))
        self.assertEqual(contract.PROD_SECRETS.service_env_files["migrate"], ("migrate.env",))

    def test_differing_database_passwords_are_refused_by_name(self) -> None:
        files = f03_files()
        files["postgres.env"][P + "DB_PASSWORD"] = "synthetic-other"
        _, _, problems = contract.derive_file_backed(files, contract.PROD)
        self.assertIn("app_db_password: differs from the password PostgreSQL was initialised with",
                      problems)


class MergedModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.base = tempfile.TemporaryDirectory(prefix="mykhaya-prod-secrets-")
        base = Path(cls.base.name)
        cls.f03_root, cls.root = base / "prod", base / "prod" / "file-backed"
        cls.root.mkdir(parents=True)
        for directory in ("field", "apple"):
            (base / directory).mkdir()
        source = f03_files()
        source["compose.env"][P + "FIELD_KEYS_HOST_DIR"] = (base / "field").as_posix()
        source["compose.env"][P + "APPLE_KEY_HOST_DIR"] = (base / "apple").as_posix()
        derived, cls.values, _ = contract.derive_file_backed(source, contract.PROD)
        for root, files in ((cls.f03_root, source), (cls.root, derived)):
            for name, values in files.items():
                (root / name).write_text("".join(
                    f"{k}={contract.format_env_value(v)}\n" for k, v in values.items()),
                    encoding="utf-8", newline="\n")
        paths = f03.Paths(ROOT, cls.f03_root / ".service-env-state", *(base / "x",) * 4)
        cls.models, cls.hashes = {}, {}
        release = f03.Release("v9.9.9", "0" * 40, "2026-01-01T00:00:00Z")
        clean = {k: v for k, v in os.environ.items() if not k.startswith(("MYKHAYA_", "COMPOSE_"))}
        with mock.patch.dict(os.environ, clean, clear=True):
            for mode, root in (("service-env", cls.f03_root), ("secrets", cls.root)):
                model = f03.render_model(paths, mode, root, release, tools=True)
                if model is None:
                    raise unittest.SkipTest("docker compose is unavailable")
                cls.models[mode] = model
                cls.hashes[mode] = {s: f03.service_hash(paths, mode, root, release, s)
                                    for s in f03.UNCHANGED_SERVICES}
        cls.model = cls.models["secrets"]
        for secret in cls.model["secrets"].values():  # only differs on a Windows workstation
            secret["file"] = secret["file"].replace("\\", "/")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.base.cleanup()

    def errors(self, model) -> list[str]:
        profile = contract.PROD_SECRETS
        return (contract.check_resolved_model(model, ROOT, profile)
                + contract.check_provenance(model, self.root, profile)
                + contract.check_secret_mounts(model, self.root, profile))

    def test_caddy_is_published_on_localhost_only(self) -> None:
        published = {name: [(p.get("host_ip"), p["published"], p["target"]) for p in service["ports"]]
                     for name, service in self.models["secrets"]["services"].items()
                     if service.get("ports")}
        self.assertEqual(published, {"caddy": [("127.0.0.1", "80", 80)]})

    def test_the_merged_model_satisfies_the_contract(self) -> None:
        self.assertEqual(self.errors(self.model), [])

    def test_no_credential_reaches_any_environment(self) -> None:
        text = json.dumps({n: s.get("environment") for n, s in self.model["services"].items()})
        for name, value in self.values.items():
            if value:
                self.assertNotIn(value.split("\n")[1] if "\n" in value else value, text, name)

    def test_only_postgres_among_the_infrastructure_services_changes(self) -> None:
        changed = {s for s in f03.UNCHANGED_SERVICES
                   if self.hashes["secrets"][s] != self.hashes["service-env"][s]}
        self.assertEqual(changed, {"postgres"})
        self.assertEqual(set(orchestrator.UNCHANGED), set(f03.UNCHANGED_SERVICES) - {"postgres"})

    def test_only_environment_and_secrets_differ_from_f03(self) -> None:
        for key in ("volumes", "networks", "name"):
            self.assertEqual(self.model[key], self.models["service-env"][key], key)
        for name, service in self.model["services"].items():
            before = self.models["service-env"]["services"][name]
            for key in set(service) | set(before):
                if key not in ("environment", "secrets", "env_file"):
                    self.assertEqual(service.get(key), before.get(key), f"{name}.{key}")

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
            ("caddy: must not receive secret secret_key", ("services", "caddy"),
             lambda s: {**s, "secrets": [{"source": "secret_key"}]}),
            ("does not come from", ("secrets", "secret_key", "file"), "/etc/mykhaya/dev/secret_key"),
            ("MYKHAYA_PROCESS_ROLE must be api",
             ("services", "api", "environment", contract.PROCESS_ROLE), "worker"),
            ("postgres: receives POSTGRES_PASSWORD", ("services", "postgres", "environment"),
             lambda e: {**e, "POSTGRES_PASSWORD": "x"}),
            ("migrate: receives MYKHAYA_PUBLIC_WEB_URL", ("services", "migrate", "environment"),
             lambda e: {**e, P + "PUBLIC_WEB_URL": "x"}),
        ):
            with self.subTest(fragment=fragment):
                errors = change(path, value)
                self.assertTrue(any(fragment in e for e in errors), errors)

    def test_the_f03_profile_refuses_the_secrets_model(self) -> None:
        self.assertTrue(contract.check_secret_mounts(self.model, None, contract.PROD))


@unittest.skipUnless(os.name == "posix", "needs a POSIX shell")
class ModeSelectionTests(unittest.TestCase):
    """prod-config-mode.sh, for every combination of states and flags."""

    def select(self, f03_state: str, secrets: str, purpose: str, **flags: str) -> str:
        with tempfile.TemporaryDirectory() as base:
            for name, value in ((".service-env-state", f03_state), (".secrets-state", secrets)):
                if value != "absent":
                    Path(base, name).write_text(value + "\n", encoding="utf-8")
            script = (f'set -eu; ROOT="{ROOT}"; die() {{ echo refused; exit 1; }}; '
                      f'. "$ROOT/infrastructure/scripts/prod-config-mode.sh"; prod_select_mode {purpose}; '
                      'echo "$PROD_CONFIG_MODE ${MYKHAYA_PROD_SECRETS:-0} ${PROD_ENV_SOURCE#$PROD_CONFIG_ROOT}"')
            result = subprocess.run(
                ["sh", "-c", script], capture_output=True, text=True,
                env={"PATH": os.environ["PATH"], **flags,
                     "MYKHAYA_PROD_SERVICE_ENV_STATE": f"{base}/.service-env-state"})
            return result.stdout.strip() if result.returncode == 0 else "refused"

    def test_every_state_combination_without_flags(self) -> None:
        allowed = {("legacy", "legacy"): "legacy", ("active", "legacy"): "service-env",
                   ("active", "active"): "secrets"}
        for pair in itertools.product(STATES, STATES):
            with self.subTest(pair=pair):
                result = self.select(*pair, "deploy")
                self.assertEqual(result.split()[0], allowed.get(pair, "refused"))

    def test_absent_state_files_mean_legacy(self) -> None:
        self.assertEqual(self.select("absent", "absent", "deploy").split()[0], "legacy")

    def test_the_shell_cannot_select_or_cancel_secrets(self) -> None:
        self.assertEqual(self.select("active", "active", "deploy", MYKHAYA_PROD_SECRETS="0"),
                         "secrets 1 /file-backed/compose.env")
        self.assertEqual(self.select("active", "legacy", "deploy", MYKHAYA_PROD_SECRETS="1"),
                         "service-env 0 /compose.env")

    def test_transition_flags(self) -> None:
        cut, back = {"MYKHAYA_PROD_SECRETS_CUTOVER": "1"}, {"MYKHAYA_PROD_SECRETS_ROLLBACK": "1"}
        for pair, flags, wanted in (
            (("active", "legacy"), cut, "secrets"), (("active", "pending"), cut, "secrets"),
            (("active", "rollback-pending"), cut, "secrets"), (("active", "active"), cut, "refused"),
            (("legacy", "legacy"), cut, "refused"), (("pending", "legacy"), cut, "refused"),
            (("active", "active"), back, "service-env"), (("active", "pending"), back, "service-env"),
            (("active", "legacy"), back, "refused"), (("active", "active"), cut | back, "refused"),
            (("active", "pending"), {"MYKHAYA_PROD_LEGACY_ENV_ROLLBACK": "1"}, "refused"),
            (("active", "active"), {"MYKHAYA_PROD_LEGACY_ENV_ROLLBACK": "1"}, "refused"),
            (("active", "active"), {"MYKHAYA_PROD_SERVICE_ENV_CUTOVER": "1"}, "refused"),
        ):
            with self.subTest(pair=pair, flags=flags):
                self.assertEqual(self.select(*pair, "deploy", **flags).split()[0], wanted)

    def test_read_only_tools_work_in_every_state(self) -> None:
        for pair in itertools.product(STATES, STATES):
            with self.subTest(pair=pair):
                self.assertIn(self.select(*pair, "readonly").split()[0],
                              {"legacy", "service-env", "secrets"})
        self.assertEqual(self.select("active", "pending", "readonly").split()[0], "secrets")
        self.assertEqual(self.select("active", "rollback-pending", "readonly").split()[0], "service-env")

    def test_an_unrecognised_state_is_refused(self) -> None:
        self.assertEqual(self.select("active", "activ", "deploy"), "refused")
        self.assertEqual(self.select("active", "activ", "readonly"), "refused")


class OrchestratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base = tempfile.TemporaryDirectory()
        self.addCleanup(self.base.cleanup)
        base = Path(self.base.name)
        self.paths = f03.Paths(ROOT, base / ".service-env-state", base / "m", base / "r", base / "c",
                               base / "d")
        self.args = argparse.Namespace(
            action="apply", expect_host="h", accept_dropped="", accept_unresolved_packages=None,
            confirm_offhost_backup="", confirm_offhost_config_backup="", confirm_key_escrow=False,
            confirm_restore_rehearsal="")

    def migration(self, f03_state="absent", secrets="absent") -> orchestrator.SecurityMigration:
        for path, value in ((self.paths.state, f03_state), (self.paths.secrets_state, secrets)):
            path.unlink(missing_ok=True)
            if value != "absent":
                path.write_text(value + "\n", encoding="utf-8")
        return orchestrator.SecurityMigration(self.paths, self.args, f03.Findings(quiet=True))

    def test_every_state_combination_maps_to_one_stage(self) -> None:
        known = {pair: stage for pair, stage in orchestrator.STAGES.items()}
        for pair in itertools.product(STATES, STATES):
            self.assertEqual(self.migration(*pair).stage, known.get(pair, "inconsistent"), pair)
        self.assertEqual(self.migration("active", "garbage").stage, "inconsistent")
        self.assertEqual(self.migration().stage, "legacy")
        self.assertEqual(set(orchestrator.NEXT), set(orchestrator.STAGES.values()))

    def test_rollback_goes_one_stage_at_a_time(self) -> None:
        for stage, target in (("legacy", None), ("f03-pending", "legacy"), ("f03-active", "legacy"),
                              ("secrets-pending", "f03"), ("secrets-active", "f03"),
                              ("secrets-rollback-pending", "f03"), ("inconsistent", None)):
            self.assertEqual(orchestrator.rollback_target(stage), target, stage)

    def test_only_the_exact_phrase_approves(self) -> None:
        for typed, approved in (("MIGRATE PROD SECRETS\n", True), ("MIGRATE PROD SECRETS", True),
                                ("", False), ("\n", False), ("yes\n", False),
                                ("migrate prod secrets\n", False), ("MIGRATE PROD SECRETS \n", False),
                                ("MIGRATE DEV\n", False)):
            with mock.patch("sys.stdin", io.StringIO(typed)), redirect_stdout(io.StringIO()):
                self.assertEqual(orchestrator.ask(orchestrator.SECRETS_PHRASE), approved, typed)

    def test_restore_evidence_is_required_and_not_in_the_future(self) -> None:
        for value, ok in (("", False), ("yes", False), ("2999-01-01", False), ("2026-01-01", True)):
            m = self.migration()
            self.args.confirm_restore_rehearsal = value
            m.check_restore_evidence()
            self.assertEqual(not m.f.errors, ok, value)

    def snapshot(self, **changes) -> dict:
        fingerprint = {"database": "1", "alembic": "a", "volumes": {"v": "t"},
                       "encrypted_failures": {"x_failed": 1}, "field_failures": {"vin_mismatch": 0}}
        fingerprint.update(changes)
        return fingerprint

    def compare(self, now: dict | Exception) -> list[str]:
        m = self.migration("active", "pending")
        m.release.head = "c"
        m.containers = {s: [{"Id": s}] for s in orchestrator.UNCHANGED}
        before = {"commit": "c", "keys": {}, "legacy_env": f03.file_metadata(self.paths.legacy_env),
                  "fingerprint": self.snapshot(),
                  "containers": {s: s for s in orchestrator.UNCHANGED}}
        effect = {"side_effect": now} if isinstance(now, Exception) else {"return_value": now}
        with mock.patch.object(m, "fingerprint", **effect):
            m.compare(before)
        return m.f.errors

    def test_the_baseline_comparison(self) -> None:
        self.assertEqual(self.compare(self.snapshot()), [])
        # A live user may add or remove encrypted rows; fewer failures are fine.
        self.assertEqual(self.compare(self.snapshot(encrypted_failures={"x_failed": 0})), [])
        for fragment, changes in (
            ("not the same PostgreSQL", {"database": "2"}), ("revision changed", {"alembic": "b"}),
            ("volume v is missing", {"volumes": {"v": "new"}}), ("volume v is missing", {"volumes": {}}),
            ("encrypted failures", {"encrypted_failures": {"x_failed": 2}}),
            ("encrypted failures", {"encrypted_failures": {}}),
            ("field failures", {"field_failures": {"vin_mismatch": 1}}),
            ("field failures", {"field_failures": "no-keyring"}),
        ):
            with self.subTest(changes=changes):
                self.assertTrue(any(fragment in e for e in self.compare(self.snapshot(**changes))))
        self.assertTrue(self.compare(RuntimeError("could not be read")))

    def test_an_edited_legacy_env_stops_a_migration_but_not_a_rollback(self) -> None:
        for secrets, fatal in (("pending", True), ("rollback-pending", False)):
            m = self.migration("active", secrets)
            m.release.head = "c"
            m.containers = {s: [{"Id": s}] for s in orchestrator.UNCHANGED}
            with mock.patch.object(m, "fingerprint", return_value=self.snapshot()):
                m.compare({"commit": "c", "keys": {}, "legacy_env": {"size": -1},
                           "fingerprint": self.snapshot(),
                           "containers": {s: s for s in orchestrator.UNCHANGED}})
            self.assertEqual(bool(m.f.errors), fatal, secrets)

    def test_restart_detection(self) -> None:
        def containers(count=0, started="t"):
            return {s: [{"Id": s, "RestartCount": count if s == "scheduler" else 0,
                         "State": {"StartedAt": started if s == "scheduler" else "t"}}]
                    for s in (*f03.APP_SERVICES, "postgres")}
        for action, before, after, failed in (
            ("apply", containers(), containers(), False),
            # A restart before verification must not strand a resume or rollback.
            ("rollback", containers(1), containers(1), False),
            ("accept", containers(1), containers(1), True),
            ("apply", containers(), containers(1, "u"), True),
            ("rollback", containers(1), containers(2, "u"), True),
            ("apply", containers(), containers(0, "u"), True),
            ("apply", containers(), {}, True),
        ):
            m = self.migration("active", "pending")
            m.args.action, m.containers = action, before
            with mock.patch.object(f03, "project_containers", return_value=after), \
                    mock.patch.object(orchestrator.time, "sleep"):
                m.check_stable()
            self.assertEqual(bool(m.f.errors), failed, (action, before, after))

    def test_environment_credentials_are_detected(self) -> None:
        m = self.migration("active", "active")
        m.containers = {"api": [{"Config": {"Env": [
            "MYKHAYA_SMTP_PASSWORD=x", "MYKHAYA_VAPID_PRIVATE_KEY=",
            "MYKHAYA_DATABASE_URL=postgresql+asyncpg://mykhaya_app:x@postgres:5432/mykhaya"]}}],
            "migrate": [{"Config": {"Env": ["MYKHAYA_SECRET_KEY=x"]}}],
            "postgres": [{"Config": {"Env": ["POSTGRES_PASSWORD=x"]}, "Mounts": []}]}
        m.check_no_environment_credentials()
        text = " ".join(m.f.errors)
        for fragment in ("api: still has MYKHAYA_SMTP_PASSWORD", "migrate: still has MYKHAYA_SECRET_KEY",
                         "database URL still holds a password", "postgres: still has POSTGRES_PASSWORD",
                         "POSTGRES_PASSWORD_FILE does not use its secret file"):
            self.assertIn(fragment, text)
        self.assertNotIn("VAPID", text)

    def test_home_migration_rule(self) -> None:
        def blocking(*rows):
            db = sqlite3.connect(":memory:")
            self.addCleanup(db.close)
            db.execute("create table p (status text, completed_at text)")
            db.executemany("insert into p values (?, ?)", rows)
            return db.execute(f"select count(*) from p where ({f03.FINISHED_PACKAGE}) is not true").fetchone()[0]
        self.assertEqual(blocking(*[("expired", None)] * 18, ("discarded", None), ("completed", "t")), 0)
        for row in (("uploaded", None), ("importing", None), ("failed", None), ("READY_TO_IMPORT", None),
                    ("unknown", None), ("completed", None), ("expired", "t"), (None, None)):
            self.assertEqual(blocking(row), 1, row)
        dev = (SCRIPTS / "dev-secrets-cutover.sh").read_text(encoding="utf-8")
        self.assertIn(f'FINISHED_PACKAGE="{f03.FINISHED_PACKAGE}"', dev)

    @unittest.skipUnless(os.name == "posix", "needs file locks")
    def test_only_one_migration_command_runs_at_a_time(self) -> None:
        root = Path(self.base.name)
        with orchestrator.exclusive(root), self.assertRaises(BlockingIOError):
            with orchestrator.exclusive(root):
                pass

    def test_contradictory_states_stop_every_action(self) -> None:
        self.migration("legacy", "active")
        for action in orchestrator.ACTIONS:
            with mock.patch.dict(os.environ, {"MYKHAYA_PROD_SERVICE_ENV_STATE": str(self.paths.state)}), \
                    mock.patch.object(f03, "project_containers", return_value={}), \
                    redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(orchestrator.main([action, "--expect-host", "h"]), 1, action)

    def test_the_f03_tool_refuses_once_docker_secrets_started(self) -> None:
        self.migration("active", "pending")
        with mock.patch.dict(os.environ, {"MYKHAYA_PROD_SERVICE_ENV_STATE": str(self.paths.state)}), \
                redirect_stderr(io.StringIO()) as err:
            self.assertEqual(f03.main(["--rollback-check"]), 1)
        self.assertIn("use prod-security-migrate.sh", err.getvalue())


class RepositoryGuards(unittest.TestCase):
    TOOLS = ("prod-security-migrate.sh", "prod_security_migration.py", "prod-deploy.sh",
             "prod-config-mode.sh", "dev_secrets_migration.py", "restore.sh")

    def text(self, name: str) -> str:
        return (SCRIPTS / name).read_text(encoding="utf-8")

    def test_nothing_destroys_rotates_or_connects_out(self) -> None:
        for name in self.TOOLS:
            text = self.text(name)
            self.assertNotRegex(text, r"volume (rm|prune)|down -v|--volumes|--renew-anon|alembic downgrade", name)
            self.assertNotRegex(text, r"openssl rand|token_urlsafe|\bssh\b|wget |make reset", name)
            self.assertNotRegex(text, r"compose[^\n]* (-y|--yes)\b", name)

    def test_orchestrator_queries_are_read_only(self) -> None:
        queries = re.findall(r'f03\.psql\(pg, "([^"]+)', self.text("prod_security_migration.py"))
        self.assertEqual(len(queries), 2)
        self.assertTrue(all(q.startswith("select ") for q in queries))

    def test_every_live_change_goes_through_the_deploy_script_after_approval(self) -> None:
        text = self.text("prod_security_migration.py")
        self.assertNotRegex(text, r'"compose", *"(up|run|down|restart|stop)')
        apply = text[text.index("def apply_secrets("):text.index("def action_accept(")]
        self.assertLess(apply.index("ask(SECRETS_PHRASE)"), apply.index("deploy(m"))
        self.assertLess(apply.index("m.verify_running("), apply.index('m.write_state("active"'))
        rollback = text[text.index("def action_rollback(m"):text.index("ACTIONS = {")]
        self.assertLess(rollback.index("ask("), rollback.index("deploy(m"))

    def test_containers_are_changed_without_terminal_input(self) -> None:
        """Compose may offer to delete a volume whose labels differ."""
        for line in self.text("prod-deploy.sh").splitlines():
            if re.search(r"prod_compose (up|run)\b", line):
                self.assertIn("</dev/null", line)

    def test_only_the_selector_and_validators_name_the_overlay(self) -> None:
        users = {p.name for p in SCRIPTS.iterdir() if p.is_file()
                 and "compose.production.secrets" in p.read_text(encoding="utf-8")}
        self.assertEqual(users, {"prod-config-mode.sh", "validate_backend_config.py",
                                 "prod_service_env_migration.py", "prod_security_migration.py"})

    def test_the_overlay_only_adds_secrets_and_roles(self) -> None:
        text = OVERLAY.read_text(encoding="utf-8")
        for key in ("volumes:", "networks:", "ports:", "image:", "command:", "user:", "privileged:"):
            self.assertNotIn(key, text)

    def test_restores_never_drop_ownership(self) -> None:
        for name in ("restore.sh", "backup-config-mode.sh"):
            self.assertNotIn("--no-owner", self.text(name))
        restore = self.text("restore.sh")
        self.assertLess(restore.index("Nothing was changed"), restore.index("pg_restore --username"))
        self.assertTrue(restore.rstrip().endswith("\nverify_restored_ownership"))

    def test_ci_runs_the_rehearsal(self) -> None:
        workflow = (ROOT / ".github/workflows/quality.yml").read_text(encoding="utf-8")
        self.assertIn("bash infrastructure/scripts/check-prod-secrets-migration.sh", workflow)


if __name__ == "__main__":
    unittest.main()
