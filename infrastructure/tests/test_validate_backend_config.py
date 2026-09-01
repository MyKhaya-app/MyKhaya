"""Regression tests for merged backend runtime configuration validation."""

import importlib.util
import sys
import unittest
from pathlib import Path

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

    def test_failure_output_does_not_include_secret_values(self):
        secret_db = "postgresql://secret-password@wrong-host:5432/mykhaya"
        values = self.base()
        values[1] = config("worker", db=secret_db)
        output = "\n".join(module.validate(values))
        self.assertNotIn(secret_db, output)
        self.assertNotIn("secret-password", output)


if __name__ == "__main__":
    unittest.main()
