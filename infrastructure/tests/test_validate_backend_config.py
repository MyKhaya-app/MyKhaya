"""Regression tests for merged backend runtime configuration validation."""

import importlib.util
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "validate_backend_config", ROOT / "infrastructure/scripts/validate_backend_config.py"
)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
sys.modules["validate_backend_config"] = module
SPEC.loader.exec_module(module)


def config(
    service: str,
    *,
    db: str = "postgresql://app@postgres:5432/mykhaya",
    redis: str = "redis://redis:6379/0",
    apns: bool = False,
    environment: str = "development",
    apns_bundle_id: str = "app.mykhaya.mobile",
):
    db_hash, db_length = module.fingerprint(db)
    redis_hash, redis_length = module.fingerprint(redis)
    secret_hash, secret_length = module.fingerprint("shared-test-session-secret")
    return module.RuntimeConfig(
        service,
        db_hash,
        db_length,
        module.database_target(db),
        redis_hash,
        redis_length,
        secret_hash,
        secret_length,
        "mailpit",
        1025,
        apns,
        environment,
        apns_bundle_id,
    )


class BackendConfigTests(unittest.TestCase):
    def base(self):
        return [config(name) for name in module.SERVICES]

    def test_matching_backend_config_passes(self):
        self.assertEqual(module.validate(self.base()), [])

    def test_worker_database_divergence_fails(self):
        values = self.base()
        values[1] = config("worker", db="postgresql://wrong@postgres:5432/mykhaya")
        self.assertIn("worker database_url differs from api", module.validate(values))

    def test_scheduler_database_divergence_fails(self):
        values = self.base()
        values[2] = config("scheduler", db="postgresql://app@wrong-host:5432/mykhaya")
        self.assertIn("scheduler database_url differs from api", module.validate(values))

    def test_migrate_database_target_divergence_fails(self):
        values = self.base()
        values[3] = config("migrate", db="postgresql://migrator@wrong-host:5432/mykhaya")
        self.assertIn("migrate database target differs from api", module.validate(values))

    def test_migrate_role_credentials_do_not_false_fail(self):
        values = self.base()
        values[3] = config("migrate", db="postgresql://migrator@postgres:5432/mykhaya")
        self.assertEqual(module.validate(values), [])

    def test_worker_only_apns_configuration_does_not_false_fail(self):
        values = self.base()
        values[1] = config("worker", apns=True)
        self.assertEqual(module.validate(values), [])

    def production(self, *, apns: bool, apns_bundle_id: str):
        values = [config(name, environment="production", apns_bundle_id="") for name in module.SERVICES]
        values[1] = config("worker", environment="production", apns=apns, apns_bundle_id=apns_bundle_id)
        return values

    def test_production_with_the_prod_apns_topic_passes(self):
        values = self.production(apns=True, apns_bundle_id="app.mykhaya.mobile.prod")
        self.assertEqual(module.validate(values), [])

    def test_production_with_the_dev_apns_topic_fails(self):
        values = self.production(apns=True, apns_bundle_id="app.mykhaya.mobile")
        self.assertEqual(
            module.validate(values),
            [
                "worker APNs topic (MYKHAYA_APNS_BUNDLE_ID) is 'app.mykhaya.mobile', "
                "expected 'app.mykhaya.mobile.prod' for the production app"
            ],
        )

    def test_production_with_an_empty_apns_topic_fails(self):
        values = self.production(apns=True, apns_bundle_id="")
        self.assertEqual(len(module.validate(values)), 1)

    def test_production_without_apns_delivery_ignores_the_topic(self):
        values = self.production(apns=False, apns_bundle_id="app.mykhaya.mobile")
        self.assertEqual(module.validate(values), [])

    def test_development_apns_topic_is_not_held_to_the_production_app(self):
        values = self.base()
        values[1] = config("worker", apns=True, apns_bundle_id="app.mykhaya.mobile")
        self.assertEqual(module.validate(values), [])

    def test_probe_record_carries_environment_and_apns_topic(self):
        record = module.parse_config(
            "worker",
            'MYKHAYA_RUNTIME_CONFIG={"database_hash":"db","database_length":2,"database_target":"postgresql://postgres:5432/db","redis_hash":"r","redis_length":1,"secret_hash":"s","secret_length":1,"smtp_host":"mailpit","smtp_port":1025,"apns_delivery_configured":true,"environment":"production","apns_bundle_id":"app.mykhaya.mobile.prod"}',
        )
        self.assertEqual(record.environment, "production")
        self.assertEqual(record.apns_bundle_id, "app.mykhaya.mobile.prod")

    def test_failure_output_does_not_include_secret_values(self):
        secret_db = "postgresql://secret-password@wrong-host:5432/mykhaya"
        values = self.base()
        values[1] = config("worker", db=secret_db)
        output = "\n".join(module.validate(values))
        self.assertNotIn(secret_db, output)
        self.assertNotIn("secret-password", output)

    def test_probe_project_isolated_per_process(self):
        project = module.probe_project_name()
        self.assertTrue(project.startswith("mykhaya-config-probe-"))
        self.assertNotEqual(project, "mykhaya")

    def test_compose_command_keeps_exact_merged_files_and_isolates_project(self):
        command = module.compose_command("mykhaya-config-probe-123")
        self.assertEqual(
            command,
            [
                "docker",
                "compose",
                "-p",
                "mykhaya-config-probe-123",
                "-f",
                "compose.yml",
                "-f",
                "compose.dev.yml",
            ],
        )

    def test_probe_command_reuses_image_without_requesting_a_build(self):
        context = module.ProbeContext(
            "mykhaya-config-probe-123",
            (
                "docker",
                "compose",
                "-p",
                "mykhaya-config-probe-123",
                "-f",
                "compose.yml",
                "-f",
                "compose.dev.yml",
                "-f",
                "C:/temp/images.yml",
            ),
            Path("C:/temp/images.yml"),
        )
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='MYKHAYA_RUNTIME_CONFIG={"database_hash":"db","database_length":2,"database_target":"postgresql://postgres:5432/db","redis_hash":"r","redis_length":1,"secret_hash":"s","secret_length":1,"smtp_host":"mailpit","smtp_port":1025,"apns_delivery_configured":false}\n',
            stderr="",
        )
        with mock.patch.object(module.subprocess, "run", return_value=completed) as run:
            module.container_probe("api", context)
        command = run.call_args.args[0]
        self.assertNotIn("--build", command)
        self.assertIn("--no-deps", command)
        self.assertIn("--rm", command)
        self.assertIn("mykhaya-config-probe-123", command)

    def test_service_env_mode_uses_the_dev_root_and_overlay(self):
        with mock.patch.dict(module.os.environ, {"MYKHAYA_DEV_CONFIG_ROOT": "/etc/mykhaya/dev"}):
            command = module.compose_command("mykhaya-config-probe-1")
            env = module.compose_environment()
        self.assertEqual(
            command,
            ["docker", "compose", "-p", "mykhaya-config-probe-1", "--env-file",
             "/etc/mykhaya/dev/compose.env", "-f", "compose.yml", "-f", "compose.dev.yml",
             "-f", "compose.dev.service-env.yml"],
        )
        for name in module.BLANKED_INTERPOLATION:
            self.assertEqual(env[name], "")

    def test_production_ignores_the_dev_root(self):
        with mock.patch.dict(
            module.os.environ,
            {"MYKHAYA_DEV_CONFIG_ROOT": "/etc/mykhaya/dev", "MYKHAYA_PRODUCTION": "1"},
        ):
            self.assertIsNone(module.service_env_root())
            self.assertIsNone(module.compose_environment())
            self.assertNotIn("--env-file", module.base_compose_args())

    def test_service_env_skips_only_comparisons_the_contract_removes(self):
        values = self.base()
        values[3] = config("migrate", redis="redis://unset-default:6379/0")
        values[2] = config("scheduler")
        values[2] = module.RuntimeConfig(**{**values[2].__dict__, "smtp_host": "mailpit-default"})
        self.assertEqual(module.validate(values, service_env=True), [])
        legacy = module.validate(values)
        self.assertIn("migrate redis_url differs from api", legacy)
        self.assertIn("scheduler SMTP connection differs from api", legacy)
        # A scheduler that is given SMTP (monitoring) must still match api.
        values[2] = module.RuntimeConfig(**{**values[2].__dict__, "email_delivery_configured": True})
        self.assertIn("scheduler SMTP connection differs from api",
                      module.validate(values, service_env=True))
        # Worker SMTP and every session secret are always compared.
        values[1] = module.RuntimeConfig(**{**values[1].__dict__, "smtp_port": 2525})
        self.assertIn("worker SMTP connection differs from api",
                      module.validate(values, service_env=True))

    def resolved(self, volumes):
        return {
            "name": "mykhaya",
            "services": {name: {"build": {}} for name in module.SERVICES},
            "volumes": volumes,
        }

    def override_for(self, volumes, environment):
        with mock.patch.dict(module.os.environ, environment):
            if "MYKHAYA_PRODUCTION" not in environment:
                module.os.environ.pop("MYKHAYA_PRODUCTION", None)
            context = module.create_probe_context(self.resolved(volumes))
        try:
            return context, context.override_path.read_text(encoding="utf-8")
        finally:
            context.override_path.unlink(missing_ok=True)
            context.override_path.parent.rmdir()

    def test_every_declared_volume_is_probe_owned(self):
        volumes = {
            "postgres_data": {"name": "mykhaya_postgres_data"},
            "home_migration_data": {"name": "mykhaya_prod_home_migration_data"},
            "explicit": {"name": "mykhaya_explicit"},
        }
        self.assertEqual(module.probe_owned_volumes({"volumes": volumes}),
                         ["explicit", "home_migration_data", "postgres_data"])

    def test_external_volumes_fail_closed(self):
        with self.assertRaises(module.ProbeIsolationError) as raised:
            module.probe_owned_volumes({"volumes": {"shared": {"name": "x", "external": True}}})
        self.assertIn("shared", str(raised.exception))

    def test_dev_and_production_probes_never_name_application_volumes(self):
        volumes = {
            "home_migration_data": {"name": "mykhaya_dev_home_migration_data"},
            "postgres_data": {"name": "mykhaya_postgres_data"},
        }
        for environment in ({}, {"MYKHAYA_PRODUCTION": "1"}):
            with self.subTest(environment=environment):
                context, override = self.override_for(volumes, environment)
                for key in volumes:
                    self.assertIn(f'name: "{context.project_name}_{key}"', override)
                self.assertNotIn("mykhaya_dev_home_migration_data", override)
                self.assertNotIn('"mykhaya_postgres_data"', override)

    def test_probe_project_names_are_collision_resistant(self):
        names = {module.probe_project_name() for _ in range(50)}
        self.assertEqual(len(names), 50)
        self.assertTrue(all(re.fullmatch(r"mykhaya-config-probe-\d+-[0-9a-f]{8}", n) for n in names))

    def isolation_with(self, model, existing=()):
        context = module.ProbeContext("probe-x", ("docker", "compose", "-p", "probe-x"), Path("o.yml"))

        def fake_run(command, **kwargs):
            if command[:3] == ["docker", "volume", "inspect"]:
                return subprocess.CompletedProcess(command, 0 if command[3] in existing else 1, "", "")
            return subprocess.CompletedProcess(command, 0, json.dumps(model), "")

        with mock.patch.object(module.subprocess, "run", side_effect=fake_run):
            module.verify_probe_isolation(context)

    def test_isolation_verification_accepts_only_probe_owned_resources(self):
        good = {"volumes": {"a": {"name": "probe-x_a"}}, "networks": {"edge": {"name": "probe-x_edge"}}}
        self.isolation_with(good)
        for bad, fragment in (
            ({"volumes": {"a": {"name": "mykhaya_dev_home_migration_data"}}}, "volume a is not probe-scoped"),
            ({"volumes": {"a": {"name": "x", "external": True}}}, "volume a is external"),
            ({"networks": {"edge": {"name": "mykhaya_edge"}}}, "network edge is not probe-scoped"),
        ):
            with self.subTest(fragment=fragment), self.assertRaises(module.ProbeIsolationError) as raised:
                self.isolation_with(bad)
            self.assertIn(fragment, str(raised.exception))
        with self.assertRaises(module.ProbeIsolationError) as raised:
            self.isolation_with(good, existing=("probe-x_a",))
        self.assertIn("volume a already exists", str(raised.exception))

    def test_cleanup_never_uses_down_volumes_and_removes_only_owned_volumes(self):
        context = module.ProbeContext("probe-x", ("docker", "compose", "-p", "probe-x"), Path("missing/o.yml"))
        calls = []

        def fake_run(command, **kwargs):
            calls.append(command)
            if command[:3] == ["docker", "volume", "ls"]:
                # Label filter output; a stray non-prefixed name must never be removed.
                listed = "probe-x_a\nmykhaya_dev_home_migration_data\n"
                return subprocess.CompletedProcess(command, 0, listed, "")
            return subprocess.CompletedProcess(command, 0, "", "")

        with mock.patch.object(module.subprocess, "run", side_effect=fake_run):
            module.cleanup_probe(context)
        self.assertNotIn("--volumes", calls[0])
        self.assertIn("down", calls[0])
        self.assertIn("label=com.docker.compose.project=probe-x", calls[1])
        removed = [c[3] for c in calls if c[:3] == ["docker", "volume", "rm"]]
        self.assertEqual(removed, ["probe-x_a"])

    def test_compose_failure_diagnostics_redact_connection_values(self):
        result = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="failed redis://user:password@redis:6379/0 password=secret-value",
        )
        error = module.compose_failure("probe", result)
        self.assertIn("probe failed with exit code 1", str(error))
        self.assertNotIn("user:password@redis", str(error))
        self.assertNotIn("secret-value", str(error))


if __name__ == "__main__":
    unittest.main()
