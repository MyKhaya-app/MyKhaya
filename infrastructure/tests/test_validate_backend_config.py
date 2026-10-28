"""Regression tests for merged backend runtime configuration validation."""

import importlib.util
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
